"""The git implementation of `Vcs`: one repository and its worktrees.

Layer: core. This file holds the repository, ref, and worktree operations;
`merges.py` holds commits, diffs, and merges, and `_runner.py` holds the
subprocess plumbing both build on. `Git` is the whole of the API in one class —
the split is a file size limit, not a seam anyone outside `impl/` can see.

Only `cli.py` constructs this. Workflows take a `Vcs`.
"""

from pathlib import Path

from agl.core.vcs.api import (
    BranchExistsError,
    DirtyWorktreeError,
    FileStatus,
    UnknownRefError,
    Vcs,
    VcsError,
    Worktree,
)
from agl.core.vcs.impl.merges import MergeOps

__all__ = ["Git"]


class Git(MergeOps, Vcs):
    """`Vcs` over a real repository, found from any path inside it."""

    # -- repository -------------------------------------------------------

    def root(self) -> Path:
        return self._root

    def current_branch(self, cwd: Path | None = None) -> str:
        result = self._run(["symbolic-ref", "--quiet", "--short", "HEAD"], cwd, check=False)
        if result.code != 0:
            raise VcsError(f"HEAD is detached in {cwd if cwd is not None else self._root}")
        return result.stdout.strip()

    def is_dirty(self, cwd: Path | None = None) -> bool:
        return bool(self._porcelain(cwd))

    def status(self, cwd: Path | None = None) -> tuple[FileStatus, ...]:
        return tuple(sorted(self._porcelain(cwd), key=lambda entry: entry.path))

    def discard_changes(self, cwd: Path) -> None:
        # Two commands because git has no one command for it: `reset --hard`
        # only speaks for what is tracked, and `clean` only for what is not.
        # `-fd` and not `-fdx`, so what `.gitignore` covers survives.
        self._run(["reset", "--hard"], cwd)
        self._run(["clean", "-fd"], cwd)

    # -- refs -------------------------------------------------------------

    def rev_parse(self, ref: str) -> str:
        # `^{commit}` so a ref that exists but names no commit is not a sha.
        result = self._run(
            ["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], None, check=False
        )
        if result.code != 0 or not result.stdout.strip():
            raise UnknownRefError(ref)
        return result.stdout.strip()

    def ref_exists(self, ref: str) -> bool:
        return self._ref_exists(ref)

    def branch_exists(self, name: str) -> bool:
        return self._ref_exists(f"refs/heads/{name}")

    def branches(self, prefix: str = "") -> tuple[str, ...]:
        result = self._run(["for-each-ref", "--format=%(refname:short)", "refs/heads/"], None)
        names = (line for line in result.stdout.splitlines() if line)
        return tuple(sorted(name for name in names if name.startswith(prefix)))

    def create_branch(self, name: str, base: str) -> None:
        with self._lock:
            self._create_branch(name, base)

    def delete_branch(self, name: str, force: bool = False) -> None:
        with self._lock:
            flag = "-D" if force else "-d"
            result = self._run(["branch", flag, "--", name], None, check=False)
            if result.code == 0:
                return
            if not self.branch_exists(name):
                raise UnknownRefError(name)
            raise VcsError(f"cannot delete branch {name}: {self._reason(result)}")

    def merge_base(self, a: str, b: str) -> str:
        result = self._run(["merge-base", a, b], None, check=False)
        if result.code == 0:
            return result.stdout.strip()
        self._require_refs(a, b)
        # Exit 1 with both refs resolving means unrelated histories.
        raise VcsError(f"no merge base for {a} and {b}")

    def is_ancestor(self, maybe_ancestor: str, descendant: str) -> bool:
        # Exit code is the answer: 0 yes, 1 no, 128 something did not resolve.
        result = self._run(
            ["merge-base", "--is-ancestor", maybe_ancestor, descendant], None, check=False
        )
        if result.code in (0, 1):
            return result.code == 0
        self._require_refs(maybe_ancestor, descendant)
        raise VcsError(f"cannot compare {maybe_ancestor} and {descendant}: {self._reason(result)}")

    # -- worktrees --------------------------------------------------------

    def add_worktree(self, path: Path, branch: str, base: str) -> Worktree:
        with self._lock:
            self._create_branch(branch, base)
            path.parent.mkdir(parents=True, exist_ok=True)
            result = self._run(["worktree", "add", str(path), branch], None, check=False)
            if result.code != 0:
                # The branch was ours to make, so it is ours to take back — a
                # failed add must not leave a half-created branch behind.
                self._run(["branch", "-D", "--", branch], None, check=False)
                raise VcsError(f"cannot add worktree at {path}: {self._reason(result)}")
            return Worktree(path=path.resolve(), branch=branch)

    def attach_worktree(self, path: Path, branch: str) -> Worktree:
        with self._lock:
            # Asked in advance, unlike everywhere else in this file: git says
            # the same thing when the branch is missing as when it is held by
            # another tree, and those are different answers to the caller.
            if not self.branch_exists(branch):
                raise UnknownRefError(branch)
            path.parent.mkdir(parents=True, exist_ok=True)
            result = self._run(["worktree", "add", str(path), branch], None, check=False)
            if result.code != 0:
                raise VcsError(f"cannot attach worktree at {path}: {self._reason(result)}")
            return Worktree(path=path.resolve(), branch=branch)

    def remove_worktree(self, path: Path, force: bool = False) -> None:
        with self._lock:
            target = path.resolve()
            if target not in {worktree.path for worktree in self._worktrees()}:
                raise VcsError(f"no worktree registered at {path}")
            if not force and self.is_dirty(cwd=path):
                raise DirtyWorktreeError(f"worktree at {path} has uncommitted changes")
            argv = ["worktree", "remove", str(path)]
            if force:
                argv.insert(2, "--force")
            result = self._run(argv, None, check=False)
            if result.code != 0:
                raise VcsError(f"cannot remove worktree at {path}: {self._reason(result)}")

    def list_worktrees(self) -> tuple[Worktree, ...]:
        return self._worktrees()

    def prune_worktrees(self) -> None:
        with self._lock:
            self._run(["worktree", "prune"], None)

    # -- internals --------------------------------------------------------

    def _create_branch(self, name: str, base: str) -> None:
        """Creates a branch, mapping git's refusal onto the API's errors.

        Not locked: both public callers hold it already.
        """
        result = self._run(["branch", "--", name, base], None, check=False)
        if result.code == 0:
            return
        if self.branch_exists(name):
            raise BranchExistsError(name)
        if not self._ref_exists(base):
            raise UnknownRefError(base)
        raise VcsError(f"cannot create branch {name}: {self._reason(result)}")

    def _worktrees(self) -> tuple[Worktree, ...]:
        """Parses `worktree list --porcelain` — never the human-readable form.

        A detached-HEAD entry has no `branch` line and is skipped, not guessed at.
        """
        result = self._run(["worktree", "list", "--porcelain"], None)
        worktrees: list[Worktree] = []
        path: Path | None = None
        for line in result.stdout.splitlines():
            if line.startswith("worktree "):
                path = Path(line[len("worktree ") :])
            elif line.startswith("branch ") and path is not None:
                ref = line[len("branch ") :]
                worktrees.append(Worktree(path=path.resolve(), branch=_short_branch(ref)))
            elif not line:
                path = None
        return tuple(worktrees)


def _short_branch(ref: str) -> str:
    """`refs/heads/topic/one` -> `topic/one`."""
    prefix = "refs/heads/"
    return ref[len(prefix) :] if ref.startswith(prefix) else ref
