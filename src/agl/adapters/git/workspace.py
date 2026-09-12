from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from agl.adapters.git._runner import GitRunner, unreadable
from agl.adapters.git._trees import (
    _Place,
    _place,
    delete,
    make,
    namespaces_in,
    registry_lock,
    run_lock,
    tidy,
)
from agl.ports.errors import ConflictError, NotFoundError, UpstreamUnexpected
from agl.ports.ids import Namespace, RunLabel
from agl.ports.tree_layout import TreesRoot, run_trees_dir, worktree_branch_prefix
from agl.ports.workspace import Workspace, WorkspaceProvider

__all__ = ["GitWorkspaceProvider"]

_ASKING: Final = 30.0

# git's worktree registry in the `-z` form (git 2.36): every attribute ends in a NUL and an empty
# attribute ends the record, which the newline form documents itself as unable to promise.
_ATTRIBUTE_END: Final = "\0"
_REGISTERED_AT: Final = "worktree "
_REGISTERED_ON: Final = "branch "

# `git worktree lock` writes a reason or nothing, and the reason may hold newlines - which is the
# whole of why the `-z` form exists and why the attribute is matched rather than split.
_LOCKED: Final = "locked"
_LOCKED_FOR: Final = "locked "

# `rev-parse` resolves `refs/tags/<name>` before `refs/heads/<name>`, so a short name in a
# repository holding both answers about the tag.
_BRANCH_REF: Final = "refs/heads/"

# `for-each-ref` matches its pattern with wildmatch in pathname mode (git 2.50, measured), so `*`
# stops at a `/` and this reads one segment below the prefix and never two. `lstrip=2` drops
# `refs/heads/` and leaves the branch spelled the way `tree_layout` composes it. `ids.py` admits no
# `*`, `?` or `[` into a `RunLabel`, so the prefix this joins onto holds no metacharacter to escape.
_ONE_SEGMENT: Final = "*"

class GitWorkspaceProvider(WorkspaceProvider):
    def __init__(self, repository: Path, trees: TreesRoot) -> None:
        self._git = GitRunner(repository)
        self._trees = trees

    async def open(self, label: RunLabel, namespace: Namespace | None, base: str) -> Workspace:
        place = _place(self._trees, label, namespace)
        if place.path.is_dir():
            held = await self._branch_at(place.path)
            if held == place.branch:
                return _GitWorkspace(place, self._git)
            if held is not None:
                raise ConflictError(
                    f"the checkout at {place.path} is on {held!r} and not on {place.branch!r}, so "
                    f"it is somebody else's line of work in this run's place. Nothing was changed"
                )

        attaching = await self._branch_exists(place.branch)
        make(run_trees_dir(self._trees, label))
        adding = (
            ("worktree", "add", "--end-of-options", str(place.path), place.branch)
            if attaching
            else ("worktree", "add", "-b", place.branch, "--end-of-options", str(place.path), base)
        )
        async with registry_lock(self._trees):
            await self._git.run("worktree", "prune", refusal=UpstreamUnexpected, timeout=_ASKING)
            await self._git.run(*adding, refusal=ConflictError)
        return _GitWorkspace(place, self._git)

    # Asked of git and never of the ledger, because the ledger cannot answer it: `steps.py`'s
    # `_namespace` cuts a checkout and its branch before `journal.step` writes anything, so a child
    # whose first step dies is recorded nowhere and `Store.namespaces` walks past it. The branch is
    # the half that costs work - `open` above attaches to a branch that exists and ignores the base
    # it was handed - and the registry is the half that finds a checkout whose branch somebody else
    # took away. `tests/test_clear.py` holds both.
    async def residue(self, label: RunLabel) -> tuple[Namespace, ...]:
        prefix = worktree_branch_prefix(label)
        found = [branch[len(prefix) :] for branch in await self._branches_under(prefix)]
        directory = run_trees_dir(self._trees, label).resolve()
        found.extend(
            registered.path.name
            for registered in await self._registrations()
            if registered.path.parent == directory
        )
        return namespaces_in(found)

    # What `remove` clears is the registration at this place's own path, and it clears it by
    # deleting the directory and pruning: `git worktree prune` declines a locked registration even
    # once its directory has gone (git 2.50, measured), and `git branch --delete` then refuses the
    # branch that registration still holds. A registration somewhere else entirely holds the branch
    # just as firmly and `remove` never reaches it. Either one makes `discard` refuse, and `discard`
    # is spent after checkouts and branches elsewhere in the run have already been taken away -
    # which is what `api.clear` calls this ahead of all of them to avoid.
    async def check_removable(self, label: RunLabel, namespace: Namespace | None) -> None:
        place = _place(self._trees, label, namespace)
        for registered in await self._registrations():
            if registered.branch != place.branch:
                continue
            if registered.locked:
                raise ConflictError(_under_lock(place.branch, registered.path))
            if registered.path != place.path.resolve():
                raise ConflictError(_held_elsewhere(place.branch, registered.path))

    async def remove(self, label: RunLabel, namespace: Namespace | None) -> None:
        place = _place(self._trees, label, namespace)
        delete(place.path)
        tidy(run_trees_dir(self._trees, label))
        async with registry_lock(self._trees):
            await self._git.run("worktree", "prune", refusal=UpstreamUnexpected, timeout=_ASKING)

    async def discard(self, label: RunLabel, namespace: Namespace | None) -> None:
        place = _place(self._trees, label, namespace)
        try:
            await self._git.run(
                "branch",
                "--delete",
                "--force",
                "--end-of-options",
                place.branch,
                refusal=ConflictError,
                timeout=_ASKING,
            )
        except ConflictError:
            if await self._branch_exists(place.branch):
                raise

    def hold(self, label: RunLabel) -> AbstractAsyncContextManager[None]:
        return run_lock(run_trees_dir(self._trees, label), str(label))

    async def _branch_at(self, path: Path) -> str | None:
        # Both sides resolved: git records a worktree's real path, and `/tmp` is a symlink on macOS
        # - so a trees root reached through one would register under one spelling and be looked up
        # under another.
        wanted = path.resolve()
        for registered in await self._registrations():
            if registered.path == wanted:
                return registered.branch
        return None

    async def _branches_under(self, prefix: str) -> tuple[str, ...]:
        listing = await self._git.run(
            "for-each-ref",
            "--format=%(refname:lstrip=2)",
            "--end-of-options",
            f"{_BRANCH_REF}{prefix}{_ONE_SEGMENT}",
            refusal=UpstreamUnexpected,
            timeout=_ASKING,
        )
        return tuple(line for line in listing.splitlines() if line)

    async def _registrations(self) -> tuple[_Registered, ...]:
        listing = await self._git.run(
            "worktree", "list", "--porcelain", "-z", refusal=UpstreamUnexpected, timeout=_ASKING
        )
        return _parsed(listing)

    async def _branch_exists(self, branch: str) -> bool:
        return await self._git.answers(
            "rev-parse",
            "--verify",
            "--quiet",
            "--end-of-options",
            f"{_BRANCH_REF}{branch}",
            refusal=UpstreamUnexpected,
            timeout=_ASKING,
        )

class _GitWorkspace(Workspace):
    def __init__(self, place: _Place, git: GitRunner) -> None:
        self._at = place
        self._git = git

    @property
    def path(self) -> Path:
        return self._at.path

    @property
    def branch(self) -> str:
        return self._at.branch

    async def head(self) -> str:
        answer = await self._git.run(
            "rev-parse",
            "--verify",
            "--end-of-options",
            "HEAD",
            cwd=self.path,
            refusal=NotFoundError,
            timeout=_ASKING,
        )
        return _one(answer, "a commit id")

    async def commit_all(self, message: str) -> str:
        await self._git.run("add", "--all", cwd=self.path, refusal=UpstreamUnexpected)
        if await self._git.answers(
            "diff", "--cached", "--quiet", cwd=self.path, refusal=UpstreamUnexpected
        ):
            return await self.head()
        await self._git.run(
            "commit",
            "--no-verify",
            "--no-gpg-sign",
            "--message",
            message,
            cwd=self.path,
            refusal=UpstreamUnexpected,
        )
        return await self.head()

    async def restore(self, head: str) -> None:
        await self._git.run(
            "reset", "--hard", "--end-of-options", head, cwd=self.path, refusal=NotFoundError
        )
        await self._git.run("clean", "-ffd", cwd=self.path, refusal=UpstreamUnexpected)

@dataclass(frozen=True, slots=True)
class _Registered:
    path: Path
    branch: str | None
    locked: bool

def _parsed(listing: str) -> tuple[_Registered, ...]:
    found: list[_Registered] = []
    at: Path | None = None
    on: str | None = None
    locked = False
    for attribute in listing.split(_ATTRIBUTE_END):
        if attribute.startswith(_REGISTERED_AT):
            at = Path(attribute[len(_REGISTERED_AT) :]).resolve()
        elif not attribute:
            if at is not None:
                found.append(_Registered(at, on, locked))
            at, on, locked = None, None, False
        # An attribute ahead of the `worktree` one that opens a record describes no registration,
        # so there is nothing for it to be an attribute of and the listing is unreadable here.
        elif at is None:
            raise unreadable("a worktree registration", listing)
        elif attribute.startswith(_REGISTERED_ON):
            on = _short(attribute[len(_REGISTERED_ON) :])
        elif attribute == _LOCKED or attribute.startswith(_LOCKED_FOR):
            locked = True
    return tuple(found)

def _under_lock(branch: str, where: Path) -> str:
    return (
        f"the checkout at {where} is locked, and it is on {branch!r}: `git worktree prune` leaves "
        f"a locked registration standing even once its directory has gone, so the name cannot be "
        f"deleted while the lock is on. Nothing has been taken away - this is asked about every "
        f"checkout of the run before the first one is touched, because a clear that met the lock "
        f"part-way through would already have deleted the other checkouts and the branches under "
        f"them, and they hold work that is on no other line. `git worktree unlock {where}` and "
        f"clear again, once you know whose lock it is"
    )

def _held_elsewhere(branch: str, where: Path) -> str:
    return (
        f"{branch!r} is checked out at {where}, which is not this run's own place, so the name "
        f"cannot be deleted: nothing a clear does takes a checkout outside the run's trees "
        f"directory back. Nothing has been taken away - this is asked about every checkout of the "
        f"run before the first one is touched, because a clear that met this part-way through "
        f"would already have deleted the other checkouts and the branches under them, and they "
        f"hold work that is on no other line. `git worktree remove {where}` and clear again"
    )

def _short(ref: str) -> str:
    return ref[len(_BRANCH_REF) :] if ref.startswith(_BRANCH_REF) else ref

def _one(answer: str, what: str) -> str:
    stripped = answer.strip()
    if not stripped:
        raise unreadable(what, answer)
    return stripped
