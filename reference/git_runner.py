"""Subprocess plumbing shared by the operation groups that make up `Git`.

Layer: core. Holds the repository root, the lock, and what every group needs:
running git somewhere, reading a porcelain status, naming a failure. Nothing
outside `impl/` touches it.

Refs and paths are arguments, never interpolated into a shell string, and only
machine-readable output is parsed. Failures are classified after the fact rather
than guarded against: pre-checking every ref would triple the process count on
the path where nothing is wrong, and git checks again anyway.
"""

import threading
from pathlib import Path

from agl.core.command import ExecError, ExecResult, run
from agl.core.vcs.api import FileStatus, UnknownRefError, VcsError

__all__ = ["GitRunner"]


class GitRunner:
    """One repository, the lock over it, and the way commands reach it."""

    def __init__(self, path: Path) -> None:
        """Resolves the *main* repository root from `path`, even inside a linked worktree.

        Raises `VcsError` if `path` is not inside a git repository. The lock
        guards what mutates shared state — the worktree registry, `refs/heads` —
        which git's own per-worktree `index.lock` says nothing about.
        """
        try:
            common = self._git(["rev-parse", "--path-format=absolute", "--git-common-dir"], path)
        except FileNotFoundError as error:
            raise VcsError("git is not installed") from error
        except (ExecError, OSError) as error:
            raise VcsError(f"not a git repository: {path}") from error
        self._root = Path(common.stdout.strip()).parent.resolve()
        self._lock = threading.Lock()

    # -- running git ------------------------------------------------------

    def _run(self, argv: list[str], cwd: Path | None, check: bool = True) -> ExecResult:
        """Run a git command in a worktree, or in the main root when `cwd` is None."""
        return self._git(argv, cwd if cwd is not None else self._root, check)

    @staticmethod
    def _git(argv: list[str], cwd: Path, check: bool = True) -> ExecResult:
        """Run git in `cwd`. PATH resolution is left to the exec itself."""
        return run(["git", *argv], cwd=cwd, check=check)

    @staticmethod
    def _reason(result: ExecResult) -> str:
        """The most useful thing git said about why it refused."""
        return result.stderr.strip() or result.stdout.strip() or f"exit {result.code}"

    # -- questions every group asks ---------------------------------------

    def _head(self, cwd: Path | None = None) -> str:
        """The sha `cwd` has checked out — not necessarily the main repo's HEAD."""
        return self._run(["rev-parse", "HEAD"], cwd).stdout.strip()

    def _ref_exists(self, ref: str) -> bool:
        """Whether `ref` resolves. Exit-code based, so `--quiet` and no check."""
        result = self._run(["rev-parse", "--verify", "--quiet", ref], None, check=False)
        return result.code == 0 and bool(result.stdout.strip())

    def _require_refs(self, *refs: str) -> None:
        """Raise `UnknownRefError` for the first ref that does not resolve."""
        for ref in refs:
            if not self._ref_exists(ref):
                raise UnknownRefError(ref)

    def _porcelain(self, cwd: Path | None) -> tuple[FileStatus, ...]:
        """Parses `status --porcelain=v1 -z`.

        Each field is `XY<space><path>`, the code exactly two columns, so it
        cannot be split on whitespace — ` M` would lose its meaning. A rename's
        extra original-path field is dropped. Codes come back padding-stripped.
        """
        result = self._run(["status", "--porcelain=v1", "-z"], cwd)
        fields = iter(result.stdout.split("\0"))
        entries: list[FileStatus] = []
        for field in fields:
            if not field:
                continue
            if len(field) < 4 or field[2] != " ":
                raise VcsError(f"cannot parse status entry: {field!r}")
            code, path = field[:2], field[3:]
            if code[0] in ("R", "C"):
                next(fields, None)
            entries.append(FileStatus(path=path, code=code.strip()))
        return tuple(entries)
