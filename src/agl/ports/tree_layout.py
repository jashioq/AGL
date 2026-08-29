
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from agl.ports.errors import InputError, InternalError
from agl.ports.ids import Namespace, RunLabel

__all__ = [
    "TreesRoot",
    "base_worktree",
    "run_branch",
    "run_trees_dir",
    "worktree_branch",
    "worktree_dir",
]


_BASE_DIRNAME: Final = "_base"
_WORK_INFIX: Final = "_work"
_BRANCH_PREFIX: Final = "agl"
_BRANCH_SEPARATOR: Final = "/"


@dataclass(frozen=True, slots=True)
class TreesRoot:

    path: Path

    def __post_init__(self) -> None:
        if not self.path.is_absolute():
            raise InputError(
                f"trees root {str(self.path)!r} cannot be used: it is a relative path, and a "
                f"relative root resolves against the current working directory"
            )


def run_trees_dir(trees: TreesRoot, label: RunLabel) -> Path:
    return _root(trees) / str(label)


def base_worktree(trees: TreesRoot, label: RunLabel) -> Path:
    return run_trees_dir(trees, label) / _BASE_DIRNAME


def worktree_dir(trees: TreesRoot, label: RunLabel, namespace: Namespace) -> Path:
    return run_trees_dir(trees, label) / str(namespace)


def run_branch(label: RunLabel) -> str:
    return f"{_BRANCH_PREFIX}{_BRANCH_SEPARATOR}{label}"


def worktree_branch(label: RunLabel, namespace: Namespace) -> str:
    parts = (_BRANCH_PREFIX, _WORK_INFIX, str(label), str(namespace))
    return _BRANCH_SEPARATOR.join(parts)


def _root(trees: TreesRoot) -> Path:
    if not isinstance(trees, TreesRoot):
        raise InternalError(
            f"tree_layout was given a {type(trees).__name__}, not a TreesRoot: the trees root "
            f"and AGL_HOME are different directories, and their layouts are never conflated"
        )
    return trees.path
