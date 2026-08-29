
from pathlib import Path
from typing import Final

from agl.adapters.git._changes import changes
from agl.adapters.git._runner import GitRunner, unreadable
from agl.ports.errors import NotFoundError
from agl.ports.history import FileChange, History

__all__ = ["GitHistory"]


_ASKING: Final = 30.0

_PEELED: Final = "^{commit}"

_COMPARING: Final = ("diff-tree", "-r", "--find-renames")


class GitHistory(History):

    def __init__(self, repository: Path) -> None:
        self._git = GitRunner(repository)

    async def default_ref(self) -> str:
        try:
            answer = await self._git.run(
                "symbolic-ref", "HEAD", refusal=NotFoundError, timeout=_ASKING
            )
        except NotFoundError as absent:
            raise NotFoundError(
                "this repository's HEAD names no branch - it is detached, or sitting on a state "
                "rather than on a line of work - so there is no default for a run to start from. "
                "Name one with `--from <ref>`"
            ) from absent
        return _one(answer, "a branch name")

    async def resolve(self, ref: str) -> str:
        try:
            answer = await self._git.run(
                "rev-parse",
                "--verify",
                "--end-of-options",
                f"{ref}{_PEELED}",
                refusal=NotFoundError,
                timeout=_ASKING,
            )
        except NotFoundError as absent:
            raise NotFoundError(
                f"{ref!r} names no commit in this repository. It is well-formed and this is where "
                f"a run would have started, so either it has not been created yet or it is spelled "
                f"differently here"
            ) from absent
        return _one(answer, "a commit id")

    async def exists(self, ref: str) -> bool:
        return await self._git.answers(
            "rev-parse",
            "--verify",
            "--quiet",
            "--end-of-options",
            f"{ref}{_PEELED}",
            refusal=NotFoundError,
            timeout=_ASKING,
        )

    async def contains(self, ancestor: str, descendant: str) -> bool:
        return await self._git.answers(
            "merge-base",
            "--is-ancestor",
            "--end-of-options",
            ancestor,
            descendant,
            refusal=NotFoundError,
            timeout=_ASKING,
        )

    async def changed_files(self, base: str, head: str) -> tuple[FileChange, ...]:
        return changes(
            await self._git.run(
                *_COMPARING,
                "--name-status",
                "-z",
                "--end-of-options",
                base,
                head,
                refusal=NotFoundError,
            )
        )

    async def diff(self, base: str, head: str) -> str:
        return await self._git.run(
            *_COMPARING, "--patch", "--end-of-options", base, head, refusal=NotFoundError
        )

    async def message(self, commit: str) -> str:
        return (
            await self._git.run(
                "rev-list",
                "--max-count=1",
                "--no-commit-header",
                "--format=%B",
                "--end-of-options",
                commit,
                refusal=NotFoundError,
                timeout=_ASKING,
            )
        ).rstrip()


def _one(answer: str, what: str) -> str:
    stripped = answer.strip()
    if not stripped:
        raise unreadable(what, answer)
    return stripped
