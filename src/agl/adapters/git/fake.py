from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Final
from agl.adapters.git._conflicts import already_holding, collided, unresolved
from agl.adapters.git._merging import combined, contested
from agl.adapters.git._patches import differences, patch
from agl.adapters.git._snapshots import FakeRepository, Hold, Tree
from agl.adapters.git._trees import _Place, _place, delete, make, tidy
from agl.adapters.git._working import apply, restore, snapshot
from agl.ports.errors import ConflictError, InternalError, NotFoundError, UpstreamUnexpected
from agl.ports.history import FileChange, History
from agl.ports.ids import Namespace, RunLabel
from agl.ports.integration import IntegrationOutcome, Integrator
from agl.ports.tree_layout import TreesRoot, run_trees_dir
from agl.ports.workspace import Workspace, WorkspaceProvider

__all__ = ["FakeHistory", "FakeIntegrator", "FakeRepository", "FakeWorkspaceProvider"]

_CLAIMED: Final[set[Path]] = set()

# What git's message cleanup takes away, measured character by character rather than taken from a
# definition of whitespace: a vertical tab, a form feed, U+0085 and a no-break space are all
# `str.isspace()` in Python and all ordinary characters to git, so a message of one is recorded.
_CLEANED_AWAY: Final = " \t\r\n"

class FakeWorkspaceProvider(WorkspaceProvider):
    def __init__(self, repository: FakeRepository, trees: TreesRoot) -> None:
        self._repository = repository
        self._trees = trees

    async def open(self, label: RunLabel, namespace: Namespace | None, base: str) -> Workspace:
        place = _place(self._trees, label, namespace)
        if place.path.is_dir():
            held = self._repository.checked_out_at(place.path)
            if held == place.branch:
                return _FakeWorkspace(place, self._repository)
            if held is not None:
                raise ConflictError(
                    f"the checkout at {place.path} is on {held!r} and not on {place.branch!r}, so "
                    f"it is somebody else's line of work in this run's place. Nothing was changed"
                )
            if snapshot(place.path):
                raise ConflictError(
                    f"{place.path} already exists and holds files, and nothing here has that "
                    f"place open. Something outside this run left it there; nothing was changed"
                )
        elsewhere = self._repository.checkout_of(place.branch)
        if elsewhere is not None:
            raise ConflictError(
                f"{place.branch!r} is already checked out at {elsewhere}, and one line of work "
                f"cannot be open in two places at once. Nothing was changed"
            )
        cut_from = self._repository.tip(place.branch) or self._cut_from(base, place.branch)
        make(place.path)
        self._repository.attach(place.path, place.branch, cut_from)
        restore(place.path, self._repository.tree_of(cut_from))
        return _FakeWorkspace(place, self._repository)

    async def remove(self, label: RunLabel, namespace: Namespace | None) -> None:
        place = _place(self._trees, label, namespace)
        delete(place.path)
        tidy(run_trees_dir(self._trees, label))
        self._repository.detach(place.path)
        self._repository.prune()

    async def discard(self, label: RunLabel, namespace: Namespace | None) -> None:
        place = _place(self._trees, label, namespace)
        holder = self._repository.checkout_of(place.branch)
        if holder is not None:
            raise ConflictError(
                f"{place.branch!r} is still checked out at {holder}, so the name cannot be "
                f"deleted. Take the place back first - that is what `remove` is for"
            )
        self._repository.drop(place.branch)

    def hold(self, label: RunLabel) -> AbstractAsyncContextManager[None]:
        return _claimed(run_trees_dir(self._trees, label), str(label))

    def _cut_from(self, base: str, branch: str) -> str:
        try:
            return self._repository.resolve(base)
        except NotFoundError as absent:
            raise ConflictError(
                f"{base!r} names no state in this repository, so there is nothing to cut "
                f"{branch!r} from. Nothing was changed"
            ) from absent

class _FakeWorkspace(Workspace):
    def __init__(self, place: _Place, repository: FakeRepository) -> None:
        self._at = place
        self._repository = repository

    @property
    def path(self) -> Path:
        return self._at.path

    @property
    def branch(self) -> str:
        return self._at.branch

    async def head(self) -> str:
        at = self._repository.tip(self._at.branch)
        if at is None:
            raise NotFoundError(
                f"{self._at.branch!r} names no line of work in this repository any more, so the "
                f"checkout at {self._at.path} is at no state that can be recorded"
            )
        return at

    async def commit_all(self, message: str) -> str:
        at = await self.head()
        held = snapshot(self.path)
        if held == self._repository.tree_of(at):
            return at
        _check_message(message, self.path)
        recorded = self._repository.record(held, (at,), message)
        self._repository.move(self._at.branch, recorded)
        return recorded

    async def restore(self, head: str) -> None:
        at = self._repository.resolve(head)
        restore(self.path, self._repository.tree_of(at))
        self._repository.move(self._at.branch, at)

class FakeHistory(History):
    def __init__(self, repository: FakeRepository) -> None:
        self._repository = repository

    async def default_ref(self) -> str:
        return self._repository.default_ref

    async def resolve(self, ref: str) -> str:
        return self._repository.resolve(ref)

    async def exists(self, ref: str) -> bool:
        try:
            self._repository.resolve(ref)
        except NotFoundError:
            return False
        return True

    async def contains(self, ancestor: str, descendant: str) -> bool:
        return self._repository.contains(
            self._repository.resolve(ancestor), self._repository.resolve(descendant)
        )

    async def changed_files(self, base: str, head: str) -> tuple[FileChange, ...]:
        return differences(*self._between(base, head))

    async def diff(self, base: str, head: str) -> str:
        return patch(*self._between(base, head))

    async def message(self, commit: str) -> str:
        return self._repository.message_of(self._repository.resolve(commit))

    def _between(self, base: str, head: str) -> tuple[Tree, Tree]:
        return (
            self._repository.tree_of(self._repository.resolve(base)),
            self._repository.tree_of(self._repository.resolve(head)),
        )

class FakeIntegrator(Integrator):
    def __init__(self, repository: FakeRepository) -> None:
        self._repository = repository

    async def land(self, source: Workspace, target: Workspace) -> IntegrationOutcome:
        pending = self._repository.held(target.path)
        if pending is not None:
            return IntegrationOutcome(
                conflict=already_holding(
                    _still_unresolved(pending, snapshot(target.path)),
                    source.branch,
                    target.branch,
                    target.path,
                )
            )
        landing = self._repository.tip(source.branch)
        if landing is None:
            raise UpstreamUnexpected(
                f"{source.branch!r} names no line of work in this repository, so there is nothing "
                f"there to land into {target.branch!r}"
            )
        settled = await target.head()
        if self._repository.contains(landing, settled):
            return IntegrationOutcome(head=settled)

        ancestor = self._repository.merge_base(settled, landing)
        combination = combined(
            self._repository.tree_of(ancestor) if ancestor is not None else {},
            self._repository.tree_of(settled),
            self._repository.tree_of(landing),
            target.branch,
            source.branch,
        )
        wanted = {**combination.tree, **combination.contested}
        recorded = self._repository.tree_of(settled)
        changing = frozenset(
            path
            for path in set(wanted) | set(recorded)
            if wanted.get(path) != recorded.get(path)
        )
        self._refuse_to_overwrite(target, recorded, changing)

        apply(target.path, wanted, changing)
        called = _merged(source.branch, target.branch)
        if not combination.collisions:
            arrived = self._repository.record(combination.tree, (settled, landing), called)
            self._repository.move(target.branch, arrived)
            return IntegrationOutcome(head=arrived)
        self._repository.hold(
            target.path,
            Hold(
                source=landing,
                target=settled,
                combined=combination.tree,
                collisions=combination.collisions,
                message=called,
                touched=changing,
            ),
        )
        return IntegrationOutcome(
            conflict=collided(combination.collisions, source.branch, target.branch, target.path)
        )

    async def retry(self, target: Workspace) -> IntegrationOutcome:
        pending = self._repository.held(target.path)
        if pending is None:
            raise InternalError(
                f"there is no landing pending in {target.branch!r}, so there is nothing to try "
                f"again. This is called only in answer to a conflicted outcome, and a target that "
                f"holds nothing means AGL lost track of a hold it took - or somebody finished the "
                f"landing by hand, which `abort` is the tolerant answer to"
            )
        held = snapshot(target.path)
        still = _still_unresolved(pending, held)
        if still:
            return IntegrationOutcome(conflict=unresolved(still, target.branch, target.path))
        settled = dict(pending.combined)
        for path in pending.collisions:
            resolution = held.get(path)
            if resolution is not None:
                settled[path] = resolution
        arrived = self._repository.record(
            settled, (pending.target, pending.source), pending.message
        )
        self._repository.move(target.branch, arrived)
        self._repository.release(target.path)
        return IntegrationOutcome(head=arrived)

    async def abort(self, target: Workspace) -> None:
        pending = self._repository.held(target.path)
        if pending is None:
            return
        apply(target.path, self._repository.tree_of(pending.target), pending.touched)
        self._repository.move(target.branch, pending.target)
        self._repository.release(target.path)

    def _refuse_to_overwrite(
        self, target: Workspace, recorded: Tree, changing: frozenset[str]
    ) -> None:
        held = snapshot(target.path)
        blocked = sorted(path for path in changing if held.get(path) != recorded.get(path))
        if blocked:
            raise UpstreamUnexpected(
                f"the checkout at {target.path} holds changes to {blocked} that were never "
                f"recorded, and landing {target.branch!r} would write over them. Record them or "
                f"take them away first; nothing here has been changed"
            )

@asynccontextmanager
async def _claimed(directory: Path, label: str) -> AsyncIterator[None]:
    make(directory)
    key = directory.resolve()
    if key in _CLAIMED:
        raise ConflictError(
            f"the run {label!r} is already live: something else is holding {directory}, and one "
            f"run cannot be walked twice at once. AGL takes that lock for the whole of an `agl "
            f"run` or `agl resume` and lets go of it when that ends, so wait for the invocation "
            f"that has it or stop it. Nothing here has been changed"
        )
    _CLAIMED.add(key)
    try:
        yield
    finally:
        _CLAIMED.discard(key)

def _still_unresolved(pending: Hold, held: Tree) -> tuple[str, ...]:
    return tuple(path for path in pending.collisions if contested(held.get(path)))

def _merged(source: str, target: str) -> str:
    return f"Merge branch '{source}' into {target}"

def _check_message(message: str, where: Path) -> None:
    if message.strip(_CLEANED_AWAY) == "":
        raise UpstreamUnexpected(
            f"the message for this commit is {message!r}, and git cleans that away to nothing: it "
            f"takes the trailing whitespace off every line of a `--message` and the empty lines "
            f"off both ends, then refuses what is left when nothing is - `Aborting commit due to "
            f"empty commit message.`, exit 1. Nothing in {where} has been recorded, and a step "
            f"whose commit template renders to whitespace fails here exactly as it would in anger"
        )
