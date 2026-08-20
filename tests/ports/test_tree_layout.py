"""What the trees root promises: the plan's tree, the branches, and the two words it spends.

Three things are checked here that nothing else can check. That every path stays under the
trees root, over the shared corpus, in every segment position - the same property
`test_home_layout.py` states about AGL_HOME, and the reason both files exist. That the derived
branch names are the plan's and are ones real `git check-ref-format` accepts, asked of git
rather than of a regex. And that `_base` and `_work`, the two words this layout spends on
itself, are the two words `ids.py` refuses as names, so that neither can be reached twice.

The git section at the end is the one to read first. `agl/<label>` and `agl/<label>/<namespace>`
- the naming any reader would reach for - cannot both exist in one repository, and §3.9 designs
that collision out with the `_work` infix rather than documenting it. So the tests there create
real branches in real repositories: the deliverable branch and two children coexisting, in both
creation orders, and then the same collision one level down, which is the demonstrated reason
`_work` is a reserved label rather than an asserted one.
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

# The two words the layout spends: the run's own checkout, and the infix every child branch is
# created under. Written out here rather than imported from the module, so that the test states
# the rule instead of echoing it - which is the whole of what the drift test below is worth.
_BASE: Final = "_base"
_WORK: Final = "_work"

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
    """`agl/<label>` for the run, `agl/_work/<label>/<namespace>` for a child. Nothing else."""
    assert run_branch(_AUTH) == "agl/auth"
    assert worktree_branch(_AUTH, _T01) == "agl/_work/auth/T-01"
    assert run_branch(RunLabel("billing")) == "agl/billing"
    assert worktree_branch(RunLabel("billing"), Namespace("T-02")) == "agl/_work/billing/T-02"


def test_the_run_branch_is_not_a_prefix_of_its_children_which_is_the_point_of_the_infix() -> None:
    """The one property the obvious naming had and this one deliberately does not.

    Under `agl/<label>/<namespace>` a child's ref path ran through the run's own, which is
    exactly why git could hold one or the other and never both. Anything that reconstructs a
    child branch by appending to `run_branch` reintroduces that, so the absence is pinned here
    rather than left to be noticed.
    """
    run, child = run_branch(_AUTH), worktree_branch(_AUTH, _T01)
    assert not child.startswith(f"{run}/")
    assert child.startswith(f"agl/{_WORK}/")
    assert run.split("/")[0] == child.split("/")[0] == "agl", "every ref AGL creates is agl/*"


# --- `_base` and `_work`: this layout's words, refused as names by ids.py -----------------------


def test_the_words_this_layout_spends_are_the_words_ids_refuses() -> None:
    """Two constants here and two reservations there are one decision written in two modules.

    `ids.py` is underneath this module and cannot import it, so each spells its own literal and
    this is what keeps the copies honest. `_base` is a directory name here and refused as a
    namespace there; `_work` is a branch infix here and refused as a label there. If a rename
    ever moves one and not the other, a reservation becomes a reservation against nothing, and
    this is the test that says so.
    """
    assert base_worktree(_TREES, _AUTH).name == _BASE
    with pytest.raises(InputError, match="base worktree"):
        Namespace(_BASE)

    assert worktree_branch(_AUTH, _T01).split("/")[1] == _WORK
    with pytest.raises(InputError, match="child branch"):
        RunLabel(_WORK)


def test_neither_reservation_costs_the_other_layout_a_name() -> None:
    """`agl/_base` collides with nothing, and `.trees/<label>/_work/` is a directory like any."""
    assert run_branch(RunLabel(_BASE)) == "agl/_base"
    assert worktree_dir(_TREES, _AUTH, Namespace(_WORK)) == Path("/repo/.trees/auth/_work")
    assert worktree_branch(_AUTH, Namespace(_WORK)) == "agl/_work/auth/_work"


# --- The property, over the corpus -------------------------------------------------------------


def test_property_no_accepted_name_in_any_position_escapes_the_trees_root(tmp_path: Path) -> None:
    """Every accepted value as the label and as the namespace, resolved before it is asked.

    The parts are pinned as well as the containment: a segment that silently vanished, or one
    that turned into two, would stay inside the root while addressing something else. Nothing is
    refused here any more - the one name this module used to turn away is a name `ids.py` no
    longer lets anybody build, so by the time a value reaches these functions the question has
    been settled.
    """
    root = tmp_path.resolve()
    trees = TreesRoot(root)
    for value in ACCEPTED:
        label = RunLabel(value)
        base = base_worktree(trees, label).resolve()
        assert base.is_relative_to(root), f"{value!r} escapes the trees root: {base}"
        assert base.relative_to(root).parts == (value, _BASE)
        checkout = worktree_dir(trees, label, Namespace(value)).resolve()
        assert checkout.is_relative_to(root), f"{value!r} escapes the trees root: {checkout}"
        assert checkout.relative_to(root).parts == (value, value), (
            f"{value!r} does not land where the layout says: {checkout}"
        )


# --- The branches, asked of real git -----------------------------------------------------------


@pytest.mark.skipif(shutil.which("git") is None, reason=_NO_GIT)
def test_property_every_derived_branch_name_is_one_real_git_accepts() -> None:
    """Asked of git itself, in the composed form AGL creates rather than of the bare name."""
    refnames: list[str] = []
    for value in REF_SAMPLE:
        label = RunLabel(value)
        refnames.append(f"refs/heads/{run_branch(label)}")
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


def _agl_branches(repo: Path) -> list[str]:
    """Every ref AGL made, read back from git instead of assumed from the calls that made them.

    Scoped to `refs/heads/agl/`, which is both what these tests are about and the invariant the
    `_work` infix was chosen to keep: the user's own branches are not AGL's to list.
    """
    listed = _git(repo, "for-each-ref", "--format=%(refname:strip=2)", "refs/heads/agl/")
    assert listed.returncode == 0, listed.stderr
    return sorted(listed.stdout.decode().split())


def _resolved(repo: Path, branch: str) -> str:
    """The commit a branch points at, so that "intact" can mean more than "still listed"."""
    found = _git(repo, "rev-parse", f"refs/heads/{branch}")
    assert found.returncode == 0, found.stderr
    return found.stdout.decode().strip()


@pytest.mark.skipif(shutil.which("git") is None, reason=_NO_GIT)
def test_the_run_branch_and_its_children_all_coexist_in_one_repository(tmp_path: Path) -> None:
    """What the `_work` infix buys, asked of real git rather than of the plan.

    `agl/auth` and `agl/auth/T-01` cannot both exist - `refs/heads/agl/auth` would have to be a
    file and a directory at once - and §3.9 designs that out by routing children under
    `agl/_work/<label>/`. Both creation orders are tried, because the old naming failed in both
    and a scheme that only worked in one would be no fix. Deleting the children is the other
    half of it: `agl/auth` is what the user pushes, so it has to survive the worktrees it fed,
    still pointing where it did, which is what `clear` will lean on.
    """
    run = run_branch(_AUTH)
    children = [worktree_branch(_AUTH, _T01), worktree_branch(_AUTH, Namespace("T-02"))]
    assert not git_rejects([run, *children]), "each name is legal on its own"

    for name, order in (("run-first", [run, *children]), ("children-first", [*children, run])):
        repo = _repo_with_one_commit(tmp_path, name)
        for branch in order:
            made = _git(repo, "update-ref", f"refs/heads/{branch}", "HEAD")
            assert made.returncode == 0, f"{name}: git refused {branch}: {made.stderr!r}"
        assert _agl_branches(repo) == sorted([run, *children]), f"{name}: git kept fewer"

        head = _resolved(repo, run)
        for child in children:
            removed = _git(repo, "update-ref", "-d", f"refs/heads/{child}")
            assert removed.returncode == 0, f"{name}: {removed.stderr!r}"
        assert _agl_branches(repo) == [run], f"{name}: the deliverable branch did not survive"
        assert _resolved(repo, run) == head, f"{name}: it survived, pointing somewhere else"
        assert _resolved(repo, "main") == head, f"{name}: the user's own branch was touched"


@pytest.mark.skipif(shutil.which("git") is None, reason=_NO_GIT)
def test_a_run_labelled_work_would_collide_with_every_child_branch_there_is(
    tmp_path: Path,
) -> None:
    """The reason `_work` is reserved: the identical collision, one level down.

    A run labelled `_work` would want `refs/heads/agl/_work` as its own branch - a file - while
    every child branch of every run needs `agl/_work` to be the directory above it. Each name
    passes `check-ref-format` alone, exactly as the pair §3.9 designed out did, so the
    reservation is not a matter of taste. It is refused at construction, which means the pair
    cannot be derived here at all and the offending name has to be spelled by hand to be shown -
    and showing it is the point: the reservation has a demonstrated reason, not an asserted one.
    """
    with pytest.raises(InputError, match="child branch"):
        RunLabel(_WORK)

    would_be = f"agl/{_WORK}"  # what run_branch would have returned for that label
    child = worktree_branch(_AUTH, _T01)
    assert child.startswith(f"{would_be}/"), "the run's branch would be a directory of children"
    assert not git_rejects([would_be, child]), "each name is legal on its own"

    forwards = _repo_with_one_commit(tmp_path, "work-forwards")
    assert _git(forwards, "update-ref", f"refs/heads/{would_be}", "HEAD").returncode == 0
    clash = _git(forwards, "update-ref", f"refs/heads/{child}", "HEAD")
    assert clash.returncode != 0, f"git took {child} beside {would_be}: the collision is gone"

    backwards = _repo_with_one_commit(tmp_path, "work-backwards")
    assert _git(backwards, "update-ref", f"refs/heads/{child}", "HEAD").returncode == 0
    reverse = _git(backwards, "update-ref", f"refs/heads/{would_be}", "HEAD")
    assert reverse.returncode != 0, f"git took {would_be} beside {child}: the collision is gone"


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
