"""What AGL_HOME's layout promises: the plan's tree, and one path that never leaves the root.

The layout is checked against the plan's own diagram by writing the paths out in full, because
a test that composes the answer the same way the module does agrees with any bug it has. The
property in the middle is the one that matters and the one nothing downstream re-checks: no
value `ids.py` accepts, in any segment position, at any nesting depth, can produce a path
outside the AGL_HOME it was joined onto. It is checked over the shared corpus - see
`_corpus.py` for how that is built and why it is not `hypothesis`.
"""

import hashlib
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Final

import pytest
from _corpus import ACCEPTED, CORPUS, PURE_IMPORTS, imported_modules, impurities

from agl.ports import home_layout
from agl.ports.errors import InputError, InternalError
from agl.ports.home_layout import (
    AglHome,
    RunScope,
    project_config,
    project_dir,
    run_record,
    scope_dir,
    step_dir,
    step_entry,
)
from agl.ports.ids import Namespace, ProjectName, RunLabel, StepName
from agl.ports.tree_layout import TreesRoot

_HOME: Final = AglHome(Path("/agl-home"))
_SCOPE: Final = RunScope(ProjectName("myapp"), RunLabel("auth"))
_DIGEST: Final = "9f2c4e" + "b" * 54 + "a71b"
_RUN: Final = "/agl-home/projects/myapp/runs/auth"


# --- The plan's tree, written out ------------------------------------------------------------


def test_the_layout_is_the_one_the_plan_draws() -> None:
    """Every path in plan §3.6's diagram, spelled out rather than recomposed."""
    t01 = _SCOPE.inside(Namespace("T-01"))
    assert project_config(_HOME, ProjectName("myapp")) == Path("/agl-home/projects/myapp.toml")
    assert project_dir(_HOME, ProjectName("myapp")) == Path("/agl-home/projects/myapp")
    assert scope_dir(_HOME, _SCOPE) == Path(_RUN)
    assert run_record(_HOME, _SCOPE) == Path(f"{_RUN}/run.json")
    assert step_dir(_HOME, _SCOPE, StepName("spec")) == Path(f"{_RUN}/steps/spec")
    assert step_entry(_HOME, _SCOPE, StepName("tickets"), _DIGEST) == Path(
        f"{_RUN}/steps/tickets/{_DIGEST}.json"
    )
    assert scope_dir(_HOME, t01) == Path(f"{_RUN}/worktrees/T-01")
    assert step_entry(_HOME, t01, StepName("review_quality"), _DIGEST) == Path(
        f"{_RUN}/worktrees/T-01/steps/review_quality/{_DIGEST}.json"
    )


def test_runs_are_stored_per_project_so_one_label_in_two_repos_is_two_runs() -> None:
    """Why `agl resume feat1` finds repo A's run and reports no such label in repo B."""
    label = RunLabel("feat1")
    first = scope_dir(_HOME, RunScope(ProjectName("alpha"), label))
    second = scope_dir(_HOME, RunScope(ProjectName("beta"), label))
    assert first != second
    assert not first.is_relative_to(second) and not second.is_relative_to(first)
    assert first.is_relative_to(project_dir(_HOME, ProjectName("alpha")))


def test_worktrees_nest_arbitrarily_and_inside_is_the_only_thing_that_makes_depth() -> None:
    """A step inside `T-01/worktrees/sub-b/` is a sequence of namespaces, not one."""
    deep = _SCOPE
    for name in ("T-01", "sub-b", "sub-c"):
        deep = deep.inside(Namespace(name))
    assert scope_dir(_HOME, deep) == Path(
        f"{_RUN}/worktrees/T-01/worktrees/sub-b/worktrees/sub-c"
    )
    assert step_dir(_HOME, deep, StepName("implement")).parent == scope_dir(_HOME, deep) / "steps"
    assert _SCOPE.namespaces == (), "inside() composed a new scope, it did not edit this one"
    assert deep.run == _SCOPE
    assert deep.inside(Namespace("T-01")) != deep


def test_steps_and_worktrees_are_siblings_so_one_name_cannot_be_both() -> None:
    """The plan's reason for two subtrees: `worktree("review")` and `step("review", ...)`."""
    as_step = step_dir(_HOME, _SCOPE, StepName("review"))
    as_worktree = scope_dir(_HOME, _SCOPE.inside(Namespace("review")))
    assert as_step != as_worktree
    assert not as_step.is_relative_to(as_worktree)
    assert not as_worktree.is_relative_to(as_step)
    assert as_step.parent != as_worktree.parent


def test_the_run_record_is_per_run_wherever_inside_the_run_it_is_asked_from() -> None:
    """One `run.json`, at the top. A scope three worktrees down still answers with that one."""
    deep = _SCOPE.inside(Namespace("T-01")).inside(Namespace("sub-b"))
    assert run_record(_HOME, deep) == run_record(_HOME, _SCOPE) == Path(f"{_RUN}/run.json")


# --- The property, over the corpus ------------------------------------------------------------


def test_the_corpus_is_big_enough_and_mixed_enough_to_mean_anything() -> None:
    """A corpus that accepted nothing, or rejected nothing, would pass the property below."""
    assert len(CORPUS) > 1500, f"corpus collapsed to {len(CORPUS)} values"
    assert 250 < len(ACCEPTED) < len(CORPUS) - 250, f"{len(ACCEPTED)} of {len(CORPUS)} accepted"


def test_property_no_accepted_name_in_any_position_escapes_agl_home(tmp_path: Path) -> None:
    """Every accepted value, as project, label, two nested namespaces and step, all at once.

    `.resolve()` before asking, because containment is about where a path *leads*, and a `..`
    that survived validation would only show up after normalisation. The parts are pinned as
    well as the containment: a segment that silently vanished would stay inside the root while
    addressing something else entirely.
    """
    root = tmp_path.resolve()
    home = AglHome(root)
    refused: list[str] = []
    for value in ACCEPTED:
        namespaces = (Namespace(value), Namespace(value))
        scope = RunScope(ProjectName(value), RunLabel(value), namespaces)
        try:
            entry = step_entry(home, scope, StepName(value), _DIGEST).resolve()
            config = project_config(home, ProjectName(value)).resolve()
        except InputError:
            refused.append(value)
            continue
        assert entry.is_relative_to(root), f"{value!r} escapes AGL_HOME: {entry}"
        assert config.is_relative_to(root), f"{value!r} escapes AGL_HOME: {config}"
        assert entry.relative_to(root).parts == (
            "projects", value, "runs", value, "worktrees", value, "worktrees", value,
            "steps", value, f"{_DIGEST}.json",
        ), f"{value!r} does not land where the layout says: {entry}"  # fmt: skip
        assert config.relative_to(root).parts == ("projects", f"{value}.toml")
    assert refused == [v for v in ACCEPTED if len(v.encode("utf-8")) > 250], (
        f"the only names this layout refuses are the ones .toml pushes over 255 bytes: {refused}"
    )
    assert refused, "the corpus no longer holds a name that long, so nothing was proved"


# --- The two segments no validated type vouches for --------------------------------------------


def test_a_real_sha256_hexdigest_is_the_shape_the_check_is_cut_to() -> None:
    """The check is only worth having if the thing the journal actually produces passes it."""
    digest = hashlib.sha256(b"a step fingerprint").hexdigest()
    assert step_entry(_HOME, _SCOPE, StepName("spec"), digest).name == f"{digest}.json"


@pytest.mark.parametrize(
    "digest",
    [
        "", ".", "..", "../..", "a" * 63, "a" * 65, "A" * 64, "F" * 64, "z" * 64,
        "-" + "a" * 63, "a" * 62 + "/b", "a" * 60 + ".ext", "a" * 63 + "\x00", "9f2c4e",
    ],
)  # fmt: skip
def test_a_step_entry_refuses_anything_that_is_not_a_digest(digest: str) -> None:
    """`InternalError`, not `InputError`: nobody typed this, so it is our bug and exit 70."""
    with pytest.raises(InternalError, match="not a digest"):
        step_entry(_HOME, _SCOPE, StepName("spec"), digest)


def test_a_project_name_that_fits_the_cap_but_whose_toml_file_would_not_is_refused() -> None:
    """The edge `ids.py` left: its 255-byte cap governs the name, and `.toml` adds five bytes."""
    assert str(ProjectName("x" * 255)) == "x" * 255, "ids.py caps the name, not the filename"

    fits = ProjectName("x" * 250)
    assert len(project_config(_HOME, fits).name.encode("utf-8")) == 255

    over = ProjectName("x" * 251)
    with pytest.raises(InputError, match="255") as caught:
        project_config(_HOME, over)
    assert "x" * 251 + ".toml" in str(caught.value), "the message names the file, not the name"

    # Refused for every path under `projects/<project>/`, not only for the file: a project
    # whose settings file cannot exist is not a project this layout can hold.
    with pytest.raises(InputError, match="255"):
        project_dir(_HOME, over)
    with pytest.raises(InputError, match="255"):
        scope_dir(_HOME, RunScope(over, RunLabel("auth")))


def test_the_headroom_is_measured_in_bytes_because_that_is_what_the_limit_counts() -> None:
    """`é` is one character and two bytes, and NAME_MAX has never counted characters."""
    assert project_config(_HOME, ProjectName("\xe9" * 125)).name == "\xe9" * 125 + ".toml"
    with pytest.raises(InputError, match="257"):
        project_config(_HOME, ProjectName("\xe9" * 126))


# --- The root, and the other root --------------------------------------------------------------


def test_agl_home_must_be_absolute() -> None:
    """A relative root resolves against the working directory, which this module may not read."""
    for relative in (Path("agl-home"), Path("."), Path("../agl-home"), Path("")):
        with pytest.raises(InputError, match="relative path"):
            AglHome(relative)
    assert AglHome(Path("/agl-home")).path == Path("/agl-home")


def test_a_root_and_a_scope_are_frozen_and_are_not_themselves_paths() -> None:
    """Validated once on the way in is worth nothing if the value can be edited afterwards."""
    with pytest.raises(FrozenInstanceError):
        _HOME.path = Path("/elsewhere")  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        _SCOPE.namespaces = ()  # type: ignore[misc]
    assert not hasattr(_HOME, "__fspath__"), "a root is passed to these functions, not to open()"


def test_a_trees_root_cannot_be_used_where_agl_home_belongs() -> None:
    """The two wrappers are structurally identical, so this is what tells them apart at runtime.

    `mypy --strict` rejects every call below - the ignores are that guarantee, stated
    statically, exactly as in `test_ids.py`. The asserts pin the same answer at runtime, where
    duck typing would otherwise be delighted to find a `.path` on either of them.
    """
    trees = TreesRoot(Path("/repo/.trees"))
    with pytest.raises(InternalError, match="never conflated"):
        scope_dir(trees, _SCOPE)  # type: ignore[arg-type]
    with pytest.raises(InternalError, match="TreesRoot"):
        project_config(trees, ProjectName("myapp"))  # type: ignore[arg-type]
    with pytest.raises(InternalError):
        step_entry(trees, _SCOPE, StepName("spec"), _DIGEST)  # type: ignore[arg-type]


def test_the_layout_is_pure_computation_and_imports_nothing_that_could_make_it_otherwise() -> None:
    """No `mkdir`, no `exists`, no environment, no `cwd` - and no `resolve`, which reads links.

    Read off the parsed source, so the prose above may name the things the code may not. The
    import check doubles as the other half of "never conflated": `agl.ports.tree_layout` is not
    in `PURE_IMPORTS`, so a home path can never be computed from anything that module knows.
    """
    assert impurities(home_layout) == set()
    assert imported_modules(home_layout) <= PURE_IMPORTS
