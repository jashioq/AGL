
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Final

from agl.adapters.git._runner import GitRunner, unreadable
from agl.adapters.git._trees import (
    _Place,
    _place,
    deleted,
    made,
    registry_lock,
    run_lock,
    tidied,
)
from agl.ports.errors import ConflictError, NotFoundError, UpstreamUnexpected
from agl.ports.ids import Namespace, RunLabel
from agl.ports.tree_layout import TreesRoot, run_trees_dir
from agl.ports.workspace import Workspace, WorkspaceProvider

__all__ = ["GitWorkspaceProvider"]


_ASKING: Final = 30.0

_ATTRIBUTE_END: Final = "\0"
_REGISTERED_AT: Final = "worktree "
_REGISTERED_ON: Final = "branch "

_BRANCH_REF: Final = "refs/heads/"


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
        made(run_trees_dir(self._trees, label))
        adding = (
            ("worktree", "add", "--end-of-options", str(place.path), place.branch)
            if attaching
            else ("worktree", "add", "-b", place.branch, "--end-of-options", str(place.path), base)
        )
        async with registry_lock(self._trees):
            await self._git.run("worktree", "prune", refusal=UpstreamUnexpected, timeout=_ASKING)
            await self._git.run(*adding, refusal=ConflictError)
        return _GitWorkspace(place, self._git)

    async def remove(self, label: RunLabel, namespace: Namespace | None) -> None:
        place = _place(self._trees, label, namespace)
        deleted(place.path)
        tidied(run_trees_dir(self._trees, label))
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
        listing = await self._git.run(
            "worktree", "list", "--porcelain", "-z", refusal=UpstreamUnexpected, timeout=_ASKING
        )
        wanted = path.resolve()
        registered: Path | None = None
        for attribute in listing.split(_ATTRIBUTE_END):
            if attribute.startswith(_REGISTERED_AT):
                registered = Path(attribute[len(_REGISTERED_AT) :]).resolve()
            elif attribute.startswith(_REGISTERED_ON):
                if registered is None:
                    raise unreadable("a worktree registration", listing)
                if registered == wanted:
                    return _short(attribute[len(_REGISTERED_ON) :])
            elif not attribute:
                registered = None
        return None

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


def _short(ref: str) -> str:
    return ref[len(_BRANCH_REF) :] if ref.startswith(_BRANCH_REF) else ref


def _one(answer: str, what: str) -> str:
    stripped = answer.strip()
    if not stripped:
        raise unreadable(what, answer)
    return stripped
