from dataclasses import dataclass
from pathlib import Path
from typing import Final
from agl.ports.errors import InputError, InternalError
from agl.ports.ids import Namespace, RunLabel

__all__ = [
    "BASE_DIRNAME",
    "TreesRoot",
    "base_worktree",
    "run_branch",
    "run_trees_dir",
    "worktree_branch",
    "worktree_dir",
]

# Public because a caller with no `TreesRoot` still has to name the run's own checkout - `api.clear`
# lists what it took away, and the run's own is the entry that has no `Namespace` to be named by.
BASE_DIRNAME: Final = "_base"
# Refs are files under `refs/heads/`, so `agl/<label>` and `agl/<label>/<name>` cannot both exist -
# one would have to be a file and a directory at once - in either creation order. The infix is what
# keeps them apart, and `git check-ref-format` passes each name on its own and never sees the pair.
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
    """Every working checkout belonging to one run, and nothing else.

    :param trees: where working checkouts live, which is never where AGL keeps its own state
    :param label: which run; it is the directory name as it stands, validated by `ids.py`
    :return: `<trees>/<label>/`, holding the run's own checkout and its children as siblings
    """
    return _root(trees) / str(label)

def base_worktree(trees: TreesRoot, label: RunLabel) -> Path:
    """The run's own checkout, which is what a run's children are cut from.

    :param trees: where working checkouts live, which is never where AGL keeps its own state
    :param label: which run; it takes no namespace, and no `Namespace` can spell `_base`
    :return: `<trees>/<label>/_base/`, on the branch `run_branch` composes
    """
    return run_trees_dir(trees, label) / BASE_DIRNAME

def worktree_dir(trees: TreesRoot, label: RunLabel, namespace: Namespace) -> Path:
    """One child checkout, a sibling of the run's own and of every other child.

    :param trees: where working checkouts live, which is never where AGL keeps its own state
    :param label: which run; every checkout of one run sits directly under its directory
    :param namespace: names the directory outright; the trees layout is flat, so depth is dropped
    :return: `<trees>/<label>/<namespace>/`
    """
    return run_trees_dir(trees, label) / str(namespace)

def run_branch(label: RunLabel) -> str:
    """The branch the run's own checkout is on - the deliverable, and what a user pushes.

    :param label: which run; no root, because a branch is not a path
    :return: `agl/<label>`
    """
    return f"{_BRANCH_PREFIX}{_BRANCH_SEPARATOR}{label}"

def worktree_branch(label: RunLabel, namespace: Namespace) -> str:
    """A child checkout's branch, cut from the run's own and kept clear of its name.

    :param label: which run; no root, because a branch is not a path
    :param namespace: which child; one namespace per run, since depth does not appear here
    :return: `agl/_work/<label>/<namespace>` - the infix is what lets git hold both refs at once
    """
    parts = (_BRANCH_PREFIX, _WORK_INFIX, str(label), str(namespace))
    return _BRANCH_SEPARATOR.join(parts)

def _root(trees: TreesRoot) -> Path:
    if not isinstance(trees, TreesRoot):
        raise InternalError(
            f"tree_layout was given a {type(trees).__name__}, not a TreesRoot: the trees root "
            f"and AGL_HOME are different directories, and their layouts are never conflated"
        )
    return trees.path
