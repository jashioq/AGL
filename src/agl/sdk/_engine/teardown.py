from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from agl.ports.errors import AglError, Stop
from agl.ports.history import History
from agl.ports.home_layout import RunScope
from agl.ports.ids import Namespace, RunLabel
from agl.ports.store import Store
from agl.ports.tree_layout import BASE_DIRNAME, run_branch, worktree_branch
from agl.sdk._engine.integration import Leases
from agl.sdk._engine.services import Services
from agl.sdk._engine.worktrees import Worktrees

__all__ = ["Released", "namespaces_under", "releasing"]

@dataclass(slots=True)
class Released:
    branch: str | None = None

# A run that ends deliberately gives its checkouts back; one that ends any other way keeps them.
# Neither half is tidiness: a run that failed or was cancelled is the one an operator resumes and
# the one worth going to look at, and what is worth looking at - a half-written file, the build's
# leavings, a landing somebody was part-way through - is in the checkout and on no branch.
@asynccontextmanager
async def releasing[R](
    services: Services,
    scope: RunScope,
    worktrees: Worktrees[R],
    leases: Leases,
    report: Callable[[str], None],
) -> AsyncIterator[Released]:
    released = Released()
    try:
        yield released
    except Stop:
        await _hand_back(services, scope, worktrees, leases, report)
        raise
    # A run that fanned out ends as a group, and `cli/exit_codes.py` answers 7 for one holding
    # nothing but `Stop`s - the same code a bare one gets - so both spellings of a deliberate end
    # release alike, and a group with a failure in it keeps its checkouts as a bare failure does.
    except ExceptionGroup as concurrent:
        _, failed = concurrent.split(Stop)
        if failed is None:
            await _hand_back(services, scope, worktrees, leases, report)
        raise
    else:
        released.branch = await _hand_back(services, scope, worktrees, leases, report)

async def namespaces_under(store: Store, scope: RunScope) -> tuple[Namespace, ...]:
    found: list[Namespace] = []
    for namespace in await store.namespaces(scope):
        found.append(namespace)
        found.extend(await namespaces_under(store, scope.inside(namespace)))
    return tuple(found)

async def _hand_back[R](
    services: Services,
    scope: RunScope,
    worktrees: Worktrees[R],
    leases: Leases,
    report: Callable[[str], None],
) -> str | None:
    if leases.unsettled:
        report(_holding(scope.label))
        return None
    onto = run_branch(scope.label)
    kept: list[str] = []
    for namespace in await _addressed(services.store, scope, worktrees):
        refusal = await _refused(services, scope.label, namespace, onto)
        if refusal is not None:
            kept.append(refusal)
    # `git checkout agl/<label>` answers `fatal: ... is already used by worktree at ...` while any
    # worktree holds that branch, and the run's own is the only one that can - `worktree_branch`
    # spells a child's with an infix. So the base's answer alone decides whether the branch may be
    # offered, and a run that kept it is told what stands rather than promised what it cannot take.
    held = await _refused(services, scope.label, None, onto)
    if held is not None:
        kept.append(held)
    if kept:
        report(_still_standing(scope.label, kept))
    return onto if held is None else None

# The ledger's namespaces are the ones that recorded a step, and a checkout is cut before the first
# entry is written - so a namespace that opened one and recorded nothing is in this walk's registry
# and nowhere else, and one an earlier walk recorded is in the ledger and not necessarily here.
async def _addressed[R](
    store: Store, scope: RunScope, worktrees: Worktrees[R]
) -> tuple[Namespace, ...]:
    found = list(await namespaces_under(store, scope))
    known = {namespace.collision_key for namespace in found}
    for namespace in worktrees.namespaces:
        if namespace.collision_key not in known:
            found.append(namespace)
    return tuple(found)

# `AglError` and not `Exception`: an adapter translates what it catches at its own boundary, so
# anything wider here would swallow AGL's own bug in the one place nothing else is watching.
async def _refused(
    services: Services, label: RunLabel, namespace: Namespace | None, onto: str
) -> str | None:
    try:
        await services.workspaces.remove(label, namespace)
    except AglError as refusal:
        return _unremoved(label, namespace, refusal)
    if namespace is None:
        return None
    branch = worktree_branch(label, namespace)
    try:
        if not await _landed(services.history, branch, onto):
            return _unlanded(branch, onto)
        await services.workspaces.discard(label, namespace)
    except AglError as refusal:
        return _undeleted(branch, refusal)
    return None

# `git branch -d` is the wrong question and asking it would keep every child branch there is: it
# measures a branch against the repository's own HEAD, which is whichever branch the operator has
# checked out, so a child that landed perfectly is unmerged as far as `main` is concerned - measured
# against git 2.50. The deliverable is asked about directly instead, and a name absent already has
# nothing left to lose.
async def _landed(history: History, branch: str, onto: str) -> bool:
    return not await history.exists(branch) or await history.contains(branch, onto)

# A landing nobody settled lives in the target checkout and nowhere else - git writes a conflicted
# merge into that worktree's own git directory - and taking the checkout back is a `shutil.rmtree`
# that would carry it off without a word, along with whatever a person typed into the files it
# stopped on. A live lease is one of those: `Integration` releases it on every path that settles.
def _holding(label: RunLabel) -> str:
    return (
        f'WARNING: Run "{label}" ended in the middle of a merge, so its worktrees were kept. '
        f"Run `agl resume {label}` to finish the merge."
    )

def _still_standing(label: RunLabel, kept: Sequence[str]) -> str:
    named = "\n".join(f"    {one}" for one in kept)
    return f'WARNING: Run "{label}" finished, and these were kept:\n{named}'

def _unremoved(label: RunLabel, namespace: Namespace | None, refusal: AglError) -> str:
    return f"the checkout {_addressing(label, namespace)} could not be taken back: {refusal}"

def _unlanded(branch: str, onto: str) -> str:
    return (
        f'Branch "{branch}" holds changes that never reached "{onto}". '
        f"Run `git log {onto}..{branch}` to see them."
    )

def _undeleted(branch: str, refusal: AglError) -> str:
    return f"the branch {branch!r} could not be deleted: {refusal}"

def _addressing(label: RunLabel, namespace: Namespace | None) -> str:
    return f"{label}/{BASE_DIRNAME if namespace is None else namespace}"
