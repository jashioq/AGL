import sys
from collections.abc import Callable, Mapping, Sequence
from types import MappingProxyType, ModuleType
from typing import Any, Final, assert_never
from agl.ports.agent import (
    AgentRunner,
    Capability,
    Installation,
    ModelChoice,
    ModelEfforts,
    ModelId,
    Provider,
    Standing,
    VersionRange,
    model_of,
)
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
        model = model_of(role.model)
        held = self._known.get(model)
        if held is None:
            held = await runner.capabilities(model)
            self._known[model] = held
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

async def check(
    runner: AgentRunner,
    history: History,
    declared_by: _Declaration,
    report: Callable[[str], None],
) -> None:
    try:
        await history.check_committer_identity()
    except UpstreamUnavailable as unattributable:
        raise UpstreamUnavailable(_no_identity(unattributable)) from unattributable
    declared = _declared_beside(declared_by)
    # Below the free local question and above the probes: `adapters/claude_code/runner.py`'s
    # `check_ready` spends a turn of the model it asks about, so a note arriving after it would
    # arrive after this run had been paid for, and one arriving before the question above would be
    # bought on a run that could never have committed anything.
    for note in await _notes(runner, declared):
        report(note)
    # `sorted` is stable, so two models whose probes cost the same are still asked in the order
    # `_demanded` handed them, which is the order the author wrote their roles in.
    for factory in sorted(_demanded(declared), key=_cost_of):
        try:
            await runner.check_ready(model_of(factory.model))
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
    return _PROBE_COST[model_of(factory.model).provider]

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
        first.setdefault(model_of(factory.model), factory)
    return tuple(first.values())

async def _notes(
    runner: AgentRunner, declared: tuple[RoleFactory[..., Any], ...]
) -> tuple[str, ...]:
    installations = await _installations(runner, _demanded(declared))
    found = [_version_note(one) for one in installations.values()]
    found += [_effort_note(factory, installations) for factory in _chosen(declared)]
    return tuple(note for note in found if note is not None)

# One question per provider rather than per model: `installation` describes the tool a backend
# starts and not the model it was handed, so a second model on one provider would re-read one
# binary - and `adapters/openai/_version.py` spawns twice to answer it.
async def _installations(
    runner: AgentRunner, demanded: tuple[RoleFactory[..., Any], ...]
) -> Mapping[Provider, Installation]:
    found: dict[Provider, Installation] = {}
    for factory in demanded:
        model = model_of(factory.model)
        if model.provider not in found:
            found[model.provider] = await runner.installation(model)
    return found

# De-duplicated on the whole choice where `_demanded` de-duplicates on the bare model, because this
# question is about the level a role named and two roles on one model at two levels are two of them.
def _chosen(factories: tuple[RoleFactory[..., Any], ...]) -> tuple[RoleFactory[..., Any], ...]:
    first: dict[ModelChoice, RoleFactory[..., Any]] = {}
    for factory in factories:
        if not isinstance(factory.model, ModelId):
            first.setdefault(factory.model, factory)
    return tuple(first.values())

def _version_note(installation: Installation) -> str | None:
    match installation.standing:
        case Standing.WITHIN:
            return None
        case Standing.ABOVE:
            return _above(installation)
        case Standing.BELOW:
            return _below(installation)
        case Standing.UNREADABLE:
            return _unreadable(installation)
        case Standing.UNREPORTED:
            return _unreported(installation)
        case _:
            assert_never(installation.standing)

def _effort_note(
    factory: RoleFactory[..., Any], installations: Mapping[Provider, Installation]
) -> str | None:
    choice = factory.model
    if isinstance(choice, ModelId):
        return None
    model = model_of(choice)
    installation = installations[model.provider]
    offered = installation.efforts.get(model)
    level = str(choice.effort)
    # An empty listing and a missing one say the same nothing: a tool that described no level for
    # this model has said nothing for the role's own to disagree with.
    if offered is None or not offered.levels or level in offered.levels:
        return None
    return _unlisted(factory, model, level, installation, offered)

def _above(installation: Installation) -> str:
    return (
        f"warning: {installation.tool} on this machine reports {installation.version!r}, and AGL "
        f"was tested against {_tested_range(installation.tested)}. Nothing is refused over a "
        f"version and this run carries on unchanged - a release nobody here has exercised is not a "
        f"broken one. But AGL drives that tool across an interface it does not own, so an argument "
        f"it sends or a line it reads back can have moved underneath it, and a run behaving in a "
        f"way no workflow explains is the first place to suspect that"
    )

def _below(installation: Installation) -> str:
    return (
        f"warning: {installation.tool} on this machine reports {installation.version!r}, and AGL "
        f"was tested against {_tested_range(installation.tested)}, which is newer. Nothing is "
        f"refused over a version and this run carries on unchanged, but this is the direction with "
        f"something to be done about it: AGL may send that tool an argument it does not have yet, "
        f"or read for a line it does not print yet. Updating it is the whole of the fix - there is "
        f"nothing here to silence, so the line stands on every run until the tool moves"
    )

def _unreadable(installation: Installation) -> str:
    return (
        f"warning: {installation.tool} on this machine reports {installation.version!r}, which is "
        f"not something AGL can place against the {_tested_range(installation.tested)} it was "
        f"tested against - what it orders is dotted digits and nothing else. So whether this tool "
        f"is older or newer than the range AGL knows is unknown to this run, which carries on "
        f"either way: this line names both, and the comparison is yours to make"
    )

def _unreported(installation: Installation) -> str:
    asked = (
        "AGL found no binary to ask what version it is"
        if installation.where is None
        else f"{installation.where!r} did not say what version it is when AGL asked"
    )
    return (
        f"warning: {asked}, so this run cannot place {installation.tool} against the "
        f"{_tested_range(installation.tested)} it was tested against. Nothing is refused over a "
        f"version: a backend that is genuinely not there is refused by the readiness question this "
        f"run puts next, in the tool's own words, and a version nobody could read is not that"
    )

# The levels are named in the tool's own order, `ports/agent.py`'s `ModelEfforts.levels` carrying
# it, and the last of them is named as the ceiling and never as what this step will run at: which
# level a tool substitutes for one it does not offer is nothing anybody here has measured.
def _unlisted(
    factory: RoleFactory[..., Any],
    model: ModelId,
    level: str,
    installation: Installation,
    offered: ModelEfforts,
) -> str:
    return (
        f"warning: the role factory `{factory.name}`, declared in {factory.__module__!r}, asks for "
        f"{str(model)!r} at effort {level!r}, and {installation.tool} on this machine lists no "
        f"such level for that model. What it does list, in the order it listed them, is "
        f"{', '.join(offered.levels)} - so {offered.levels[-1]!r} is the most that model reasons "
        f"at on this machine. Nothing is refused over an effort: the tool lowers a level it does "
        f"not offer rather than turning the run away, so every step on this role runs, at a level "
        f"the tool does list and not at the one the role named"
    )

def _tested_range(tested: VersionRange) -> str:
    if tested.lowest == tested.highest:
        return tested.lowest
    return f"{tested.lowest} to {tested.highest}"

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
    model = model_of(factory.model)
    return (
        f"{refusal} - and AGL asked because {str(model)!r} is the model of the role "
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
    model = model_of(role.model)
    message = (
        f"the role handed to step {step!r} cannot run on {str(model)!r}: it requires "
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
        f"on the `Role` itself, so the declaration is readable without calling the factory"
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
        f"two walks differing only in the value that was dropped would share a digest, the second "
        f"replaying the first's result. A role that needs two of something declares one type "
        f"holding both"
    )
