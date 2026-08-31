
from pathlib import Path
from typing import Final

from agl.adapters.git._conflicts import already_holding, collided, unmerged, unresolved
from agl.adapters.git._runner import GitRunner
from agl.ports.errors import InternalError, UpstreamUnexpected
from agl.ports.integration import IntegrationOutcome, Integrator
from agl.ports.workspace import Workspace

__all__ = ["GitIntegrator"]


_ASKING: Final = 30.0

_MERGING: Final = (
    "-c",
    "rerere.enabled=false",
    "merge",
    # Named because `pull.twohead = ours` is a user setting that makes a two-head merge exit 0,
    # report a head, and contain none of the child's work.
    "--strategy=ort",
    "--no-ff",
    # Both the merge and the commit that concludes one open an editor otherwise, and this child has
    # none.
    "--no-edit",
    "--no-verify",
    "--no-gpg-sign",
    "--no-verify-signatures",
    # `git merge` takes `--abort`, `--quit` and `--continue`, and `-F <path>` reads a file into the
    # message - so a branch named `--abort` would release a landing and `--file=/etc/passwd` publish
    # one.
    "--end-of-options",
)

_CONCLUDING: Final = ("commit", "--no-edit", "--no-verify", "--no-gpg-sign")

_RELEASING: Final = ("merge", "--abort")

_PENDING: Final = ("rev-parse", "--verify", "--quiet", "--end-of-options", "MERGE_HEAD")

_UNRESOLVED: Final = ("ls-files", "--unmerged", "--full-name", "-z")


class GitIntegrator(Integrator):

    def __init__(self, repository: Path) -> None:
        self._git = GitRunner(repository)

    async def land(self, source: Workspace, target: Workspace) -> IntegrationOutcome:
        if await self._held(target):
            return IntegrationOutcome(
                conflict=already_holding(
                    await self._unresolved(target), source.branch, target.branch, target.path
                )
            )
        try:
            await self._git.run(
                *_MERGING, source.branch, cwd=target.path, refusal=UpstreamUnexpected
            )
        # `git merge` exits 1 both for a conflict and for "that is not something we can merge", so
        # the exit status alone cannot tell a held target from a refused one - only asking what the
        # target is now can.
        except UpstreamUnexpected:
            if not await self._held(target):
                raise
            return IntegrationOutcome(
                conflict=collided(
                    await self._unresolved(target), source.branch, target.branch, target.path
                )
            )
        return IntegrationOutcome(head=await target.head())

    async def retry(self, target: Workspace) -> IntegrationOutcome:
        if not await self._held(target):
            raise InternalError(
                f"there is no landing pending in {target.branch!r}, so there is nothing to try "
                f"again. This is called only in answer to a conflicted outcome, and a target that "
                f"holds nothing means AGL lost track of a hold it took - or somebody finished the "
                f"landing by hand, which `abort` is the tolerant answer to"
            )
        still = await self._unresolved(target)
        if still:
            return IntegrationOutcome(conflict=unresolved(still, target.branch, target.path))
        await self._git.run(*_CONCLUDING, cwd=target.path, refusal=UpstreamUnexpected)
        return IntegrationOutcome(head=await target.head())

    async def abort(self, target: Workspace) -> None:
        if not await self._held(target):
            return
        await self._git.run(*_RELEASING, cwd=target.path, refusal=UpstreamUnexpected)

    async def _held(self, target: Workspace) -> bool:
        return await self._git.answers(
            *_PENDING, cwd=target.path, refusal=UpstreamUnexpected, timeout=_ASKING
        )

    async def _unresolved(self, target: Workspace) -> tuple[str, ...]:
        return unmerged(
            await self._git.run(
                *_UNRESOLVED, cwd=target.path, refusal=UpstreamUnexpected, timeout=_ASKING
            )
        )
