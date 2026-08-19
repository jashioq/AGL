"""What the trees root promises: the plan's tree, the branches, and the `_base` name it spends.

Three things are checked here that nothing else can check. That every path stays under the
trees root, over the shared corpus, in every segment position - the same property
`test_home_layout.py` states about AGL_HOME, and the reason both files exist. That the derived
branch names are the plan's and are ones real `git check-ref-format` accepts, asked of git
rather than of a regex. And that `_base`, which is a directory name here and a perfectly legal
`Namespace` in `ids.py`, cannot be reached twice.

The last test in the git section records a collision this deliverable did not create and could
not fix: `agl/<label>` and `agl/<label>/<namespace>` are both legal names and cannot exist in
one repository at the same time. It is pinned against real git so that the next person to meet
it finds it already written down - and so that the day the naming changes, this test fails and
says where to look.
"""

import os
import shutil
import subprocess
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Final

import pytest
from _corpus import ACCEPTED, PURE_IMPORTS, REF_SAMPLE, git_rejects, imported_modules, impurities

from agl.ports import tree_layout
from agl.ports.errors import InputError, InternalError
from agl.ports.home_layout import AglHome, RunScope, project_config, project_dir, run_record
from agl.ports.home_layout import scope_dir as home_scope_dir
from agl.ports.ids import Namespace, ProjectName, RunLabel
from agl.ports.tree_layout import (
    TreesRoot,
    base_worktree,
    run_branch,
    run_trees_dir,
    worktree_branch,
    worktree_dir,
)

_TREES: Final = TreesRoot(Path("/repo/.trees"))
_AUTH: Final = RunLabel("auth")
_T01: Final = Namespace("T-01")

# The name the layout spends on the run's own checkout, and what a `Namespace` is compared by
# when the question is whether it would land on that directory. Written out here rather than
# imported from the module, so that the test states the rule instead of echoing it.
_BASE: Final = "_base"
_BASE_KEY: Final = Namespace(_BASE).collision_key

_NO_GIT: Final = "git is not on PATH, so the git-ref properties went UNVERIFIED"


# --- The plan's tree, and the branches that go with it -----------------------------------------


def test_the_layout_is_the_one_the_plan_draws() -> None:
    """Every path in plan §3.9's diagram, spelled out rather than recomposed."""
    assert run_trees_dir(_TREES, _AUTH) == Path("/repo/.trees/auth")
    assert base_worktree(_TREES, _AUTH) == Path("/repo/.trees/auth/_base")
    assert worktree_dir(_TREES, _AUTH, _T01) == Path("/repo/.trees/auth/T-01")
    assert worktree_dir(_TREES, _AUTH, Namespace("T-02")) == Path("/repo/.trees/auth/T-02")
    billing = RunLabel("billing")
    assert base_worktree(_TREES, billing) == Path("/repo/.trees/billing/_base")
    assert worktree_dir(_TREES, billing, _T01) == Path("/repo/.trees/billing/T-01")


def test_the_checkouts_of_one_run_are_siblings_and_never_contain_each_other() -> None:
    """Flat on purpose: a worktree inside another worktree is in that one's `git status`."""
    run = run_trees_dir(_TREES, _AUTH)
    checkouts = [
        base_worktree(_TREES, _AUTH),
        worktree_dir(_TREES, _AUTH, _T01),
        worktree_dir(_TREES, _AUTH, Namespace("T-02")),
    ]
    assert [checkout.parent for checkout in checkouts] == [run, run, run]
    assert len(set(checkouts)) == len(checkouts)


def test_the_branch_derivations_are_the_plan_s() -> None:
    """`agl/<label>` for the run, `agl/<label>/<namespace>` for a child. Nothing else."""
    assert run_branch(_AUTH) == "agl/auth"
    assert worktree_branch(_AUTH, _T01) == "agl/auth/T-01"
    assert run_branch(RunLabel("billing")) == "agl/billing"
    assert worktree_branch(RunLabel("billing"), Namespace("T-02")) == "agl/billing/T-02"
    assert worktree_branch(_AUTH, _T01).startswith(f"{run_branch(_AUTH)}/")


# --- `_base`: a directory name here, and a legal Namespace in ids.py ---------------------------


def test_base_is_a_name_ids_accepts_which_is_the_whole_problem() -> None:
    """The premise. If this ever fails, the guard below is dead code and should go."""
    assert str(Namespace(_BASE)) == _BASE
    assert base_worktree(_TREES, _AUTH).name == _BASE


@pytest.mark.parametrize("spelling", ["_base", "_BASE", "_Base", "_bAsE"])
def test_no_child_worktree_may_be_called_base_in_any_spelling(spelling: str) -> None:
    """Case-folded, because `_BASE` and `_base` are one directory on a case-insensitive volume."""
    namespace = Namespace(spelling)
    with pytest.raises(InputError, match="base worktree") as caught:
        worktree_dir(_TREES, _AUTH, namespace)
    assert repr(spelling) in str(caught.value), "the message quotes what the caller passed"
    with pytest.raises(InputError, match="base worktree"):
        worktree_branch(_AUTH, namespace)


@pytest.mark.parametrize("spelling", ["base", "_bases", "__base", "_base-1", "T-01"])
def test_only_the_name_that_actually_collides_is_refused(spelling: str) -> None:
    """The cost is one name, not a family of them: over-refusing here costs a workflow author."""
    assert worktree_dir(_TREES, _AUTH, Namespace(spelling)).name == spelling
    assert worktree_branch(_AUTH, Namespace(spelling)) == f"agl/auth/{spelling}"


# --- The property, over the corpus -------------------------------------------------------------


def test_property_no_accepted_name_in_any_position_escapes_the_trees_root(tmp_path: Path) -> None:
    """Every accepted value as the label and as the namespace, resolved before it is asked.

    The parts are pinned as well as the containment: a segment that silently vanished, or one
    that turned into two, would stay inside the root while addressing something else. The
    refusals are pinned too - the guard's extent is exactly the names that fold onto `_base`,
    which is the rule stated as a set rather than as a sentence.
    """
    root = tmp_path.resolve()
    trees = TreesRoot(root)
    refused: list[str] = []
    for value in ACCEPTED:
        label = RunLabel(value)
        base = base_worktree(trees, label).resolve()
        assert base.is_relative_to(root), f"{value!r} escapes the trees root: {base}"
        assert base.relative_to(root).parts == (value, _BASE)
        try:
            checkout = worktree_dir(trees, label, Namespace(value)).resolve()
        except InputError:
            refused.append(value)
            continue
        assert checkout.is_relative_to(root), f"{value!r} escapes the trees root: {checkout}"
        assert checkout.relative_to(root).parts == (value, value), (
            f"{value!r} does not land where the layout says: {checkout}"
        )
    assert refused == [v for v in ACCEPTED if Namespace(v).collision_key == _BASE_KEY]
    assert refused, "the corpus no longer contains a spelling of _base, so nothing was proved"


# --- The branches, asked of real git -----------------------------------------------------------


@pytest.mark.skipif(shutil.which("git") is None, reason=_NO_GIT)
def test_property_every_derived_branch_name_is_one_real_git_accepts() -> None:
    """Asked of git itself, in the composed form AGL creates rather than of the bare name."""
    refnames: list[str] = []
    for value in REF_SAMPLE:
        label = RunLabel(value)
        refnames.append(f"refs/heads/{run_branch(label)}")
        if Namespace(value).collision_key != _BASE_KEY:
            refnames.append(f"refs/heads/{worktree_branch(label, Namespace(value))}")
    rejected = git_rejects(refnames)
    assert not rejected, f"git rejects {len(rejected)} of {len(refnames)}: {rejected[:10]}"


@pytest.mark.skipif(shutil.which("git") is None, reason=_NO_GIT)
def test_git_would_have_said_so_if_the_property_above_were_vacuous() -> None:
    """The control: the same helper, on names git must refuse. A stub would pass silently."""
    known_bad = ["refs/heads/agl/a b", "refs/heads/agl/a..b", "refs/heads/agl/x.lock", "@"]
    assert sorted(git_rejects(known_bad)) == sorted(known_bad)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    """Real git in one repo, with no global or system config allowed a say in the answer."""
    isolated = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, env=isolated)


def _repo_with_one_commit(parent: Path, name: str) -> Path:
    repo = parent / name
    repo.mkdir()
    assert _git(repo, "init", "-q", "-b", "main").returncode == 0
    made = _git(
        repo, "-c", "user.name=agl", "-c", "user.email=agl@example.invalid",
        "commit", "-q", "--allow-empty", "-m", "base",
    )  # fmt: skip
    assert made.returncode == 0, made.stderr
    return repo


@pytest.mark.skipif(shutil.which("git") is None, reason=_NO_GIT)
def test_the_run_branch_and_a_child_branch_cannot_both_exist_in_one_repository(
    tmp_path: Path,
) -> None:
    """A defect recorded, not a defect fixed - see this module's docstring and the module's.

    Refs are paths: `refs/heads/agl/auth` is a file, so `refs/heads/agl/auth/T-01` needs
    `agl/auth` to be a directory, and git refuses whichever of the two is created second. Both
    names pass `check-ref-format` on their own, which is why the property above is happy and
    why nothing in `ids.py` could have caught this. The derivations are the plan's, verbatim;
    the day they change, this test fails, which is the entire point of writing it down.
    """
    run, child = run_branch(_AUTH), worktree_branch(_AUTH, _T01)
    assert not git_rejects([run, child]), "each name is legal on its own"

    forwards = _repo_with_one_commit(tmp_path, "forwards")
    assert _git(forwards, "update-ref", f"refs/heads/{run}", "HEAD").returncode == 0
    clash = _git(forwards, "update-ref", f"refs/heads/{child}", "HEAD")
    assert clash.returncode != 0, f"git took {child} beside {run}: the collision is gone"

    backwards = _repo_with_one_commit(tmp_path, "backwards")
    assert _git(backwards, "update-ref", f"refs/heads/{child}", "HEAD").returncode == 0
    reverse = _git(backwards, "update-ref", f"refs/heads/{run}", "HEAD")
    assert reverse.returncode != 0, f"git took {run} beside {child}: the collision is gone"


# --- The two roots -----------------------------------------------------------------------------


def test_the_trees_root_must_be_absolute_and_is_not_itself_a_path() -> None:
    """A relative root resolves against the working directory, which this module may not read."""
    for relative in (Path(".trees"), Path("."), Path("../.trees"), Path("")):
        with pytest.raises(InputError, match="relative path"):
            TreesRoot(relative)
    with pytest.raises(FrozenInstanceError):
        _TREES.path = Path("/elsewhere")  # type: ignore[misc]
    assert not hasattr(_TREES, "__fspath__"), "a root is passed to these functions, not to git"


def test_an_agl_home_cannot_be_used_where_the_trees_root_belongs() -> None:
    """The mirror of `test_home_layout.py`'s: `mypy --strict` first, and this at runtime.

    The two wrappers are a frozen `Path` in a field called `path` and nothing else, so duck
    typing would be delighted by either. The ignores below are the static guarantee stated
    where it can be seen; the asserts are the same answer with the types thrown away.
    """
    home = AglHome(Path("/agl-home"))
    with pytest.raises(InternalError, match="never conflated"):
        run_trees_dir(home, _AUTH)  # type: ignore[arg-type]
    with pytest.raises(InternalError, match="AglHome"):
        base_worktree(home, _AUTH)  # type: ignore[arg-type]
    with pytest.raises(InternalError):
        worktree_dir(home, _AUTH, _T01)  # type: ignore[arg-type]


def test_one_run_addressed_in_both_layouts_is_two_different_places(tmp_path: Path) -> None:
    """What separates the two in the end is that `config/` hands them different directories.

    These modules cannot check that, so this checks the part they can: given even the same
    directory for both roots, no path either layout produces for a run is a path the other
    produces for it. AGL's state and AGL's checkouts are never the same location.
    """
    root = tmp_path.resolve()
    home, trees = AglHome(root), TreesRoot(root)
    for value in ACCEPTED:
        label, project = RunLabel(value), ProjectName(value)
        scope = RunScope(project, label)
        try:
            state = {
                project_dir(home, project),
                project_config(home, project),
                home_scope_dir(home, scope),
                run_record(home, scope),
            }
        except InputError:
            continue  # the `.toml` headroom, checked where it belongs
        checkouts = {run_trees_dir(trees, label), base_worktree(trees, label)}
        assert state.isdisjoint(checkouts), f"{value!r} addresses one place from two layouts"


def test_the_layout_is_pure_computation_and_imports_nothing_that_could_make_it_otherwise() -> None:
    """No worktree is created here, nothing is read, and `agl.ports.home_layout` is not imported.

    Read off the parsed source, so the prose in that module may name the things its code may
    not. `PURE_IMPORTS` holds neither layout module, which is how "neither imports the other"
    is checked rather than promised.
    """
    assert impurities(tree_layout) == set()
    assert imported_modules(tree_layout) <= PURE_IMPORTS
