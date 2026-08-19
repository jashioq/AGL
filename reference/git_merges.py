"""Commits, diffs, and merges — the half of `Git` that moves history.

Layer: core. Not usable alone: the operations `Git` inherits, split out on file
size. It runs commands and reports what git said, never opening a conflicted
file or holding an opinion about what a `<<<<<<<` means.

A conflicted merge is left in progress, for the caller to resolve and then
`commit_merge` or `abort_merge`; nothing here unwinds one silently. `merge`
takes the tree to merge *into* as `cwd`, which for a fanned-out run is the
repository root — git will not let a second tree hold a branch the root has.
"""

from pathlib import Path

from agl.core.command import ExecResult
from agl.core.vcs.api import MergeResult, VcsError
from agl.core.vcs.impl._runner import GitRunner

__all__ = ["MergeOps"]


class MergeOps(GitRunner):
    """Committing what a tree holds, diffing it, and merging it back."""

    # -- commits ----------------------------------------------------------

    def has_changes(self, cwd: Path) -> bool:
        return bool(self._porcelain(cwd))

    def commit_all(self, cwd: Path, message: str) -> str | None:
        if not self.has_changes(cwd):
            # Asked first rather than letting `git commit` fail on an empty
            # commit: "nothing changed in this tree" is an answer, not a failure.
            return None
        self._run(["add", "-A"], cwd)
        result = self._run(["commit", "-m", message], cwd, check=False)
        if result.code != 0:
            raise VcsError(f"cannot commit in {cwd}: {self._reason(result)}")
        return self._head(cwd)

    # -- diffs ------------------------------------------------------------

    def diff(self, cwd: Path, base: str, head: str) -> str:
        return self._diff(["diff", f"{base}...{head}"], cwd, base, head).stdout

    def changed_files(self, cwd: Path, base: str, head: str) -> tuple[str, ...]:
        argv = ["diff", "--name-only", "-z", f"{base}...{head}"]
        result = self._diff(argv, cwd, base, head)
        return tuple(sorted(path for path in result.stdout.split("\0") if path))

    # -- merges -----------------------------------------------------------

    def merge(self, cwd: Path, source: str, no_ff: bool = True) -> MergeResult:
        argv = ["merge", "--no-edit", "--no-ff" if no_ff else "--ff", "--", source]
        result = self._run(argv, cwd, check=False)
        if result.code == 0:
            return MergeResult(clean=True, conflicted=(), sha=self._head(cwd))
        unmerged = self.unmerged_paths(cwd)
        if unmerged:
            # Left in progress on purpose: the caller resolves and commits, or
            # aborts. There is no third state where the merge quietly vanished.
            return MergeResult(clean=False, conflicted=unmerged, sha=None)
        self._require_refs(source)
        raise VcsError(f"cannot merge {source} into {cwd}: {self._reason(result)}")

    def merge_in_progress(self, cwd: Path) -> bool:
        result = self._run(["rev-parse", "-q", "--verify", "MERGE_HEAD"], cwd, check=False)
        return result.code == 0

    def unmerged_paths(self, cwd: Path) -> tuple[str, ...]:
        result = self._run(["diff", "--name-only", "--diff-filter=U", "-z"], cwd)
        return tuple(sorted(path for path in result.stdout.split("\0") if path))

    def abort_merge(self, cwd: Path) -> None:
        result = self._run(["merge", "--abort"], cwd, check=False)
        if result.code != 0:
            raise VcsError(f"cannot abort the merge in {cwd}: {self._reason(result)}")

    def commit_merge(self, cwd: Path, message: str) -> str:
        if not self.merge_in_progress(cwd):
            # Without this, a stray call would quietly make an ordinary commit
            # out of whatever happened to be staged.
            raise VcsError(f"no merge in progress in {cwd}")
        self._stage_resolution(cwd)
        result = self._run(["commit", "-m", message], cwd, check=False)
        if result.code != 0:
            raise VcsError(f"cannot commit the merge in {cwd}: {self._reason(result)}")
        return self._head(cwd)

    # -- internals --------------------------------------------------------

    def _stage_resolution(self, cwd: Path) -> None:
        """Stages the paths this merge left unmerged, and nothing else.

        Named paths, not `add -A`: unrelated work in the tree is none of this
        merge's business. `-A` *under that pathspec* is what lets a resolver's
        deletion stage as one. Leftover conflict markers are not checked for.
        """
        unmerged = self.unmerged_paths(cwd)
        if not unmerged:
            return
        result = self._run(["add", "-A", "--", *unmerged], cwd, check=False)
        if result.code != 0:
            raise VcsError(f"cannot stage the resolution in {cwd}: {self._reason(result)}")

    def _diff(self, argv: list[str], cwd: Path, base: str, head: str) -> ExecResult:
        """Runs a `base...head` diff — three dots, always — naming a ref that will not resolve."""
        result = self._run(argv, cwd, check=False)
        if result.code != 0:
            self._require_refs(base, head)
            raise VcsError(f"cannot diff {base}...{head}: {self._reason(result)}")
        return result
