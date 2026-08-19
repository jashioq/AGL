"""Paths under the trees root - what Workspace addresses. Never conflated with home_layout.

The trees root holds working checkouts: real git worktrees with the user's code in them, one
per namespace, cut from the run's base. `AGL_HOME` holds AGL's own state and `home_layout.py`
is the only module that computes under it. Nothing here can be handed that root: this module
speaks `TreesRoot`, that one speaks `AglHome`, neither imports the other, `mypy --strict`
refuses the call, and `_root` below refuses it again at runtime because the two wrappers are
structurally identical and nothing but the class itself tells them apart.

The layout, from the plan:

    repo/                     <- the user's working dir. AGL never touches it.
    .trees/
      auth/
        _base/                <- worktree, branch agl/auth, cut from base_sha
        T-01/  T-02/          <- child worktrees, cut from agl/auth
      billing/
        _base/                <- worktree, branch agl/billing
        T-01/

and the branches that go with it: **`agl/<label>` for the run, `agl/<label>/<namespace>` for a
child**. Which directory `.trees/` itself is - beside the repo, or inside it - is `config/`'s
answer at stage 9, exactly as `$AGL_HOME` is. `TreesRoot` is that answer once it has been given.

**The trees layout is flat, and `home_layout` nests.** That asymmetry is deliberate and it is
the one thing to read twice before adding a function here. AGL's own state nests, because
`worktrees/T-01/worktrees/sub-b/` is just directories. Checkouts cannot: a worktree placed
inside another worktree's working tree appears in that one's `git status`, gets caught by its
adds and stashes, and is exactly the sort of thing an agent then commits. So every checkout in
a run is a sibling under `.trees/<label>/`, addressed by one namespace, whatever depth that
namespace holds in the run's own tree.

Everything here is a pure function of its arguments. Nothing creates a worktree, asks whether
one exists, reads the environment, or consults the current working directory: `Workspace` does
the first, and this module only says where.

Two hazards are *not* solved here. Both need a repository, or state about the run's other
namespaces, and this module is pure and knows only its arguments - so both are recorded, as
`ids.py` records its two, for the stage that has what they need.

  * **The run branch and a child branch cannot coexist in git.** Refs are paths:
    `refs/heads/agl/auth` is a file, and `refs/heads/agl/auth/T-01` needs `agl/auth` to be a
    directory, so creating the second while the first exists fails with "cannot lock ref".
    `git check-ref-format` passes each of them on its own, which is why nothing in `ids.py`
    catches it. The derivations here are the plan's, verbatim; `tests/ports/test_tree_layout.py`
    pins the collision against real git so that it cannot be discovered twice.
  * **Two namespaces at different depths flatten onto one directory.** `T-01/worktrees/sub-b`
    and a top-level `sub-b` are different scopes under `AGL_HOME` and the same
    `.trees/<label>/sub-b` here, because the checkouts are flat. Sibling uniqueness is not
    enough; what a run needs is one namespace per *run*, which is a question for whoever holds
    the run's namespace table - the same place `ids.py` sends its `collision_key`.
"""

import unicodedata
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


# The layout's own words. `_BASE_DIRNAME` is the one that a `Namespace` could also spell.
_BASE_DIRNAME: Final = "_base"
_BRANCH_PREFIX: Final = "agl"
_BRANCH_SEPARATOR: Final = "/"

# What `_BASE_DIRNAME` would be compared by if it were a name - see `_checked_namespace`. It is
# `Namespace.collision_key`'s formula and not that property, because calling the property means
# constructing `Namespace("_base")`, which is the very thing this constant exists to refuse.
# The test suite pins the two against each other, so the copy cannot drift unnoticed.
_BASE_COLLISION_KEY: Final = unicodedata.normalize("NFC", _BASE_DIRNAME.casefold())


@dataclass(frozen=True, slots=True)
class TreesRoot:
    """The root of the working checkouts, wrapped so it cannot be passed where AGL_HOME belongs.

    Both roots are directories and both are a `Path`; the wrapper is the whole of what makes
    them different. It must be absolute for the same reason `AglHome` must: a relative root
    resolves against whatever directory the process started in, and this module has promised
    not to read that.
    """

    path: Path
    """Where it is. Read it to hand the root itself to git; the layout is the functions."""

    def __post_init__(self) -> None:
        if not self.path.is_absolute():
            raise InputError(
                f"trees root {str(self.path)!r} cannot be used: it is a relative path, and a "
                f"relative root resolves against the current working directory"
            )


def run_trees_dir(trees: TreesRoot, label: RunLabel) -> Path:
    """`.trees/<label>/` - every checkout belonging to one run, and nothing else."""
    return _root(trees) / str(label)


def base_worktree(trees: TreesRoot, label: RunLabel) -> Path:
    """`.trees/<label>/_base/` - the run's own checkout, on `agl/<label>`, cut from its base.

    It takes no namespace, and `worktree_dir` refuses the one namespace that would land here.
    The two are disjoint by construction rather than by care.
    """
    return run_trees_dir(trees, label) / _BASE_DIRNAME


def worktree_dir(trees: TreesRoot, label: RunLabel, namespace: Namespace) -> Path:
    """`.trees/<label>/<namespace>/` - one child checkout, a sibling of `_base` and of the rest."""
    return run_trees_dir(trees, label) / _checked_namespace(namespace)


def run_branch(label: RunLabel) -> str:
    """`agl/<label>` - the branch the run's base worktree is on.

    A branch is not a path, so this takes no root: it is here because the trees layout is what
    the branches name, and one file owning both keeps them from drifting apart.
    """
    return f"{_BRANCH_PREFIX}{_BRANCH_SEPARATOR}{label}"


def worktree_branch(label: RunLabel, namespace: Namespace) -> str:
    """`agl/<label>/<namespace>` - the branch a child worktree is on, cut from `agl/<label>`.

    See the module docstring: git cannot hold this and `run_branch(label)` at the same time.
    That is the plan's naming, reproduced exactly, and it is recorded there rather than quietly
    changed here.
    """
    return f"{run_branch(label)}{_BRANCH_SEPARATOR}{_checked_namespace(namespace)}"


def _root(trees: TreesRoot) -> Path:
    """The one place this module reads its root, and so the one place it can be the wrong root.

    The runtime half of "never conflated"; `home_layout._root` is the other, and its docstring
    carries the reasoning. `InternalError`, because a caller mixed up two roots that `config/`
    handed it, and no user typed that.
    """
    if not isinstance(trees, TreesRoot):
        raise InternalError(
            f"tree_layout was given a {type(trees).__name__}, not a TreesRoot: the trees root "
            f"and AGL_HOME are different directories, and their layouts are never conflated"
        )
    return trees.path


def _checked_namespace(namespace: Namespace) -> str:
    """A namespace, refused if it is the name this layout has already spent on the base worktree.

    `_base` is a literal directory in the trees layout and `Namespace("_base")` breaks none of
    `ids.py`'s rules, so `worktree("_base")` would hand a workflow the run's own base checkout
    and its own branch under the name of a child - silently, and only in this layout, since
    `AGL_HOME` has no `_base` in it. Refusing it is one line here; noticing it later is a
    worktree writing over the branch every other worktree was cut from.

    Refused at this composition site rather than in `ids.py`, because `_base` is this module's
    word: `ids.py` states that all its types accept exactly the same language from one
    validator, and `RunLabel("_base")` and `ProjectName("_base")` are perfectly good names that
    collide with nothing. The cost is that nobody may name a worktree `_base`, which is the
    same shape of cost as `ids.py`'s own "nobody may name a run `-fix`".

    Compared by `collision_key` rather than by string, because on a case-insensitive volume -
    macOS by default - `_BASE` and `_base` are one directory, and a check that let `_BASE`
    through would be a check that only failed on other people's machines.
    """
    if namespace.collision_key == _BASE_COLLISION_KEY:
        raise InputError(
            f"namespace {str(namespace)!r} cannot be used: {_BASE_DIRNAME!r} is the run's own "
            f"base worktree in the trees layout, so a child worktree of that name would be the "
            f"same directory - and on a case-insensitive filesystem, so is any spelling of it"
        )
    return str(namespace)
