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

and the branches that go with it: **`agl/<label>` for the run, `agl/_work/<label>/<namespace>`
for a child**. The `_work` infix is not decoration, and it is the one derivation here worth
reading twice. Refs are files under `refs/heads/`, so the obvious scheme - `agl/auth` for the
run and `agl/auth/T-01` for its child - **cannot exist in git**, in either creation order:

    fatal: cannot lock ref 'refs/heads/agl/auth/T-01': 'refs/heads/agl/auth' exists
    fatal: cannot lock ref 'refs/heads/agl/auth': 'refs/heads/agl/auth/T-01' exists

`agl/auth` would have to be a file and a directory at once. `git check-ref-format` passes each
name on its own, which is why "must be a legal ref" does not catch it and why nothing in
`ids.py` could have: the fix belongs in the naming, and this is it. Routing children under
`agl/_work/` keeps the deliverable branch cleanly named - the user pushes `agl/auth`, not
`agl/auth/_base` - keeps every ref AGL creates under the `agl/*` invariant, and costs one extra
glob at `clear`. `tests/ports/test_tree_layout.py` pins the whole scheme against real git, in
both creation orders, so that the day it changes the test says where to look.

The two words this layout spends on itself, `_base` and `_work`, are refused as names by
`ids.py` - `_base` as a namespace, `_work` as a label, each in every spelling (§3.3). They are
refused there rather than here because a name that cannot be constructed cannot reach a
composition site at all, and because a downstream re-check that can never fire is not a guard.

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

One hazard is *not* solved here. It needs state about the run's other namespaces, and this
module is pure and knows only its arguments - so it is recorded, as `ids.py` records its one,
for the stage that has what it needs:

  * **Two namespaces at different depths flatten onto one directory.** `T-01/worktrees/sub-b`
    and a top-level `sub-b` are different scopes under `AGL_HOME` and the same
    `.trees/<label>/sub-b` here, because the checkouts are flat. Sibling uniqueness is not
    enough; what a run needs is one namespace per *run*, which is a question for whoever holds
    the run's namespace table - the same place `ids.py` sends its `collision_key`.
"""

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


# The layout's own words. `_BASE_DIRNAME` and `_WORK_INFIX` are the two that a name could also
# spell, and `ids.py` is where each is refused - as a namespace and as a label respectively.
_BASE_DIRNAME: Final = "_base"
_WORK_INFIX: Final = "_work"
_BRANCH_PREFIX: Final = "agl"
_BRANCH_SEPARATOR: Final = "/"


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

    It takes no namespace, and no `Namespace` can spell `_base`: `ids.py` refuses that name at
    construction, so the run's own checkout and its children are disjoint before anything
    reaches this module.
    """
    return run_trees_dir(trees, label) / _BASE_DIRNAME


def worktree_dir(trees: TreesRoot, label: RunLabel, namespace: Namespace) -> Path:
    """`.trees/<label>/<namespace>/` - one child checkout, a sibling of `_base` and of the rest."""
    return run_trees_dir(trees, label) / str(namespace)


def run_branch(label: RunLabel) -> str:
    """`agl/<label>` - the branch the run's base worktree is on.

    A branch is not a path, so this takes no root: it is here because the trees layout is what
    the branches name, and one file owning both keeps them from drifting apart.
    """
    return f"{_BRANCH_PREFIX}{_BRANCH_SEPARATOR}{label}"


def worktree_branch(label: RunLabel, namespace: Namespace) -> str:
    """`agl/_work/<label>/<namespace>` - a child worktree's branch, cut from `agl/<label>`.

    Not `agl/<label>/<namespace>`, which is the scheme a reader expects and which git cannot
    hold beside `run_branch(label)` in either order - see the module docstring. The infix moves
    every child one level out of the deliverable branch's way, which is what makes the pair
    legal rather than merely lucky, and it is why `ids.py` refuses `_work` as a label.

    Composed from `run_branch`'s parts rather than from `run_branch` itself: the run's branch is
    not a prefix of this one, and writing it as though it were is how the two would drift back
    into the collision the infix exists to prevent.
    """
    parts = (_BRANCH_PREFIX, _WORK_INFIX, str(label), str(namespace))
    return _BRANCH_SEPARATOR.join(parts)


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
