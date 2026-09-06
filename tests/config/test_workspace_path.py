"""The one place in `src/` that writes to `sys.path`, driven against workspaces under `tmp_path`.

`agl/config/workspace_path.py` is what makes a workflow the operator wrote importable at all: a
`Discovery` point's value is a dotted module name, and `EntryPoint.load()` resolves it through
`sys.path` exactly as `import` does. So the assertions below come in two kinds, and both are here
because neither is worth much alone - what lands on `sys.path`, which is the mechanism, and what an
`EntryPoint` synthesised out of a project file can then load, which is the thing anybody cares
about.

## Every workflow package here is named once and never again

A module imported in one test stays in `sys.modules` for the rest of the session, and restoring
`sys.path` does not take it back out. Two tests that both built a `triage` package under their own
`tmp_path` would therefore be measuring each other: the second one's `import triage.roles` would
hand back the first one's module, from a directory pytest has since deleted, and the case that
asserts a load *fails* before the insertion would fail for having succeeded earlier. Hence
`_ALPHA` through `_ZETA` - unlovely names whose whole job is to be unique in this process, and
`_VENV_DEPENDENCY`, which is the same rule for the one module planted inside a venv rather than
under `workflows/`.

## The order the entries go on in is the assertion, not a detail of it

`extend` appends and never inserts, so everything the environment AGL was started from already
provides keeps resolving from the entry it already resolved from. That is what
`test_an_agl_package_sitting_in_the_workspace_venv_never_displaces_the_running_one` is about, and
it is a claim about the operator's machine rather than about this suite: a workspace venv is the
operator's own directory and may hold anything at all, `agl` itself included.

## The second function here writes a file and puts nothing on the path

`write_editor_pth` is what `agl sync` calls once uv has finished, and it is the odd one out twice
over: it writes rather than reads, and nothing in AGL reads back what it wrote. `site` processes a
`.pth` while it builds `sys.path` for the interpreter that owns the venv, and `extend` reaches that
same directory with `sys.path.append`, which processes nothing - so
`test_writing_the_path_file_puts_nothing_on_this_processs_import_path` is the assertion that keeps
the two apart, and every claim about an editor resolving `agl.sdk` through the file is outside what
this suite can measure.

## What this file cannot assert, said plainly

Nothing here builds a venv - no `uv`, no `subprocess`, and nothing that runs an interpreter. What
stands in for one is a directory tree at the path `workspace_site_packages` composes, made for the
`lib/` subdirectory name this interpreter really installs into, which is read here from
`sysconfig.get_path("purelib")` rather than from the substituted base `src/` uses. The two
derivations agreeing is what
`test_a_workspace_venv_that_exists_is_admitted_ahead_of_the_workflows_directory` measures; a
`src/` that computed the segment from `sys.version_info` would pass on this machine and fail on a
free-threaded build, so the disagreement it would catch is a real one and not a tautology.
"""

import sys
import sysconfig
from importlib import import_module
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Final
import pytest
import agl
from agl.config.registry import GROUP, discovered
from agl.config.workspace_path import extend, write_editor_pth
from agl.ports.home_layout import (
    AglHome,
    workflows_dir,
    workspace_dir,
    workspace_editor_pth,
    workspace_site_packages,
)

# Six workflow package names and one distribution's, each spent by at most one test - see this
# module's docstring for why a second use of one would be a measurement of the first test rather
# than of the code.
_ALPHA: Final = "probe_workflow_alpha"
_BETA: Final = "probe_workflow_beta"
_GAMMA: Final = "probe_workflow_gamma"
_DELTA: Final = "probe_workflow_delta"
_EPSILON: Final = "probe_workflow_epsilon"
_ZETA: Final = "probe_workflow_zeta"
_VENV_DEPENDENCY: Final = "probe_venv_dependency"

def _home(tmp_path: Path) -> AglHome:
    """An AGL_HOME nothing else can reach, built rather than resolved so no variable is read."""
    return AglHome(tmp_path / "home")

def _workflow(home: AglHome, named: str, marker: str) -> Path:
    """One workflow shaped as an operator writes it: project file, package, and a `roles.py`.

    Every one of them spells its module `roles.py` deliberately. That is the collision two
    workflows would have if the insertion named each workflow directory rather than the one
    directory holding them all.
    """
    directory = workflows_dir(home) / named
    directory.mkdir(parents=True)
    (directory / "pyproject.toml").write_text(
        f'[project]\nname = "{named}"\nversion = "0.1.0"\n\n'
        f'[project.entry-points."{GROUP}"]\n{named} = "{named}.roles:MARKER"\n',
        encoding="utf-8",
    )
    (directory / "__init__.py").write_text("", encoding="utf-8")
    (directory / "roles.py").write_text(f'MARKER = "{marker}"\n', encoding="utf-8")
    return directory

def _point(named: str) -> EntryPoint:
    """The entry point `discovered` synthesises for `_workflow(named)`, built here by hand.

    By hand rather than through `discovered`, because `discovered` extends the path itself - so a
    point that came from it could never be asked what happens to a load before the insertion.
    """
    return EntryPoint(name=named, value=f"{named}.roles:MARKER", group=GROUP)

def _segment() -> str:
    """The `lib/` subdirectory this interpreter installs into, read off its own real `purelib`."""
    return Path(sysconfig.get_path("purelib")).parent.name

def _venv(home: AglHome) -> Path:
    """A stand-in workspace venv: the `site-packages` directory and nothing else in it."""
    site = workspace_site_packages(home, _segment())
    site.mkdir(parents=True)
    return site

# --- what lands on the path, and in what order --------------------------------------------------

def test_the_workflows_directory_itself_goes_on_the_path_and_not_each_workflow_under_it(
    tmp_path: Path,
) -> None:
    """One entry for the container, so a workflow is a package named after its own directory."""
    home = _home(tmp_path)
    directory = _workflow(home, _ALPHA, "alpha")
    extend(home)
    assert str(workflows_dir(home)) in sys.path
    assert str(directory) not in sys.path

def test_a_workspace_venv_that_exists_is_admitted_ahead_of_the_workflows_directory(
    tmp_path: Path,
) -> None:
    """Two entries in the order a workflow needs them: its dependencies, then the workflow.

    The venv directory is built at the segment this interpreter really installs into, and `src/`
    composes its own from a base handed to `sysconfig`. The two agreeing is the assertion.
    """
    home = _home(tmp_path)
    site = _venv(home)
    extend(home)
    assert sys.path.index(str(site)) < sys.path.index(str(workflows_dir(home)))

def test_a_workspace_with_no_venv_puts_only_its_workflows_directory_on_the_path(
    tmp_path: Path,
) -> None:
    """A workflow importing nothing past `agl` needs no venv, and AGL creates none to find."""
    home = _home(tmp_path)
    _workflow(home, _BETA, "beta")
    extend(home)
    assert [entry for entry in sys.path if entry.startswith(str(home.path))] == [
        str(workflows_dir(home))
    ]

def test_a_venv_built_by_another_interpreter_is_skipped_without_a_word_about_it(
    tmp_path: Path,
) -> None:
    """A venv whose `lib/` subdirectory names a different interpreter is a directory not there."""
    home = _home(tmp_path)
    stale = workspace_site_packages(home, "python0.1")
    stale.mkdir(parents=True)
    extend(home)
    assert str(stale) not in sys.path
    assert str(workflows_dir(home)) in sys.path

def test_every_entry_is_appended_so_the_environment_agl_started_in_keeps_winning(
    tmp_path: Path,
) -> None:
    """Appended, never inserted: what resolved before still resolves from the entry it did."""
    home = _home(tmp_path)
    _venv(home)
    before = list(sys.path)
    extend(home)
    assert sys.path[: len(before)] == before

def test_an_agl_package_sitting_in_the_workspace_venv_never_displaces_the_running_one(
    tmp_path: Path,
) -> None:
    """The workspace venv is the operator's own directory and may hold anything, `agl` included.

    Two guarantees rather than one, and they are separate. `agl` is imported before any of this
    runs, so `sys.modules` answers for the package itself; `agl.__path__` is then a single
    directory, which is what keeps a module the workspace copy holds and the real one does not from
    being reachable as `agl.<something>` either.
    """
    home = _home(tmp_path)
    site = _venv(home)
    (site / "agl").mkdir()
    (site / "agl" / "__init__.py").write_text("IMPOSTER = True\n", encoding="utf-8")
    (site / "agl" / "only_in_the_venv.py").write_text("VALUE = 1\n", encoding="utf-8")
    extend(home)
    assert not hasattr(agl, "IMPOSTER")
    with pytest.raises(ModuleNotFoundError):
        import_module("agl.only_in_the_venv")

# --- calling it more than once ------------------------------------------------------------------

def test_calling_twice_with_one_home_leaves_exactly_one_entry_for_each_directory(
    tmp_path: Path,
) -> None:
    """`api` reaches discovery once per command today and there is nothing promising it always
    will, so a second call has to cost nothing rather than lengthen the path every time."""
    home = _home(tmp_path)
    site = _venv(home)
    extend(home)
    extend(home)
    assert sys.path.count(str(site)) == 1
    assert sys.path.count(str(workflows_dir(home))) == 1

def test_a_second_home_adds_its_own_entries_and_takes_away_none_of_the_first(
    tmp_path: Path,
) -> None:
    """Two homes in one process accumulate, and the earlier one keeps the precedence it had.

    Nothing here can know the first home is finished with: a module imported out of it is in
    `sys.modules` already, and its submodules are found through the entry that is being proposed
    for removal. So the entries are never taken off, and a process that resolves two homes reads
    them in the order it asked for them.
    """
    first = AglHome(tmp_path / "first")
    second = AglHome(tmp_path / "second")
    extend(first)
    extend(second)
    assert sys.path.index(str(workflows_dir(first))) < sys.path.index(str(workflows_dir(second)))

# --- what an entry point can then load ----------------------------------------------------------

def test_a_synthesised_entry_point_loads_its_workflow_module_only_once_the_path_is_extended(
    tmp_path: Path,
) -> None:
    """The whole deliverable in one case: the same point, refused before and resolved after."""
    home = _home(tmp_path)
    _workflow(home, _GAMMA, "the gamma workflow")
    point = _point(_GAMMA)
    with pytest.raises(ModuleNotFoundError):
        point.load()
    extend(home)
    assert point.load() == "the gamma workflow"

def test_two_workflows_each_holding_a_roles_module_both_load_without_shadowing_each_other(
    tmp_path: Path,
) -> None:
    """What inserting the container rather than each workflow buys, stated as the collision it
    avoids: the two modules arrive as `<workflow>.roles` and are two modules, not one."""
    home = _home(tmp_path)
    _workflow(home, _DELTA, "the delta workflow")
    _workflow(home, _EPSILON, "the epsilon workflow")
    extend(home)
    assert _point(_DELTA).load() == "the delta workflow"
    assert _point(_EPSILON).load() == "the epsilon workflow"

def test_a_workflow_imports_a_third_party_module_out_of_the_workspace_venv(
    tmp_path: Path,
) -> None:
    """What the venv entry is for, stated as the thing an operator asked `agl sync` to buy.

    The planted module stands in for a distribution `uv sync` installed. It is reachable under no
    other name and from no other directory, so the marker the point hands back can only have come
    through the venv entry - and the workflow that imports it is never installed there itself,
    which is what `--no-install-workspace` in `adapters/uv/syncer.py` keeps true.
    """
    home = _home(tmp_path)
    site = _venv(home)
    (site / f"{_VENV_DEPENDENCY}.py").write_text('VERSION = "9.9.9"\n', encoding="utf-8")
    directory = _workflow(home, _ZETA, "replaced by the marker the venv supplies")
    (directory / "roles.py").write_text(
        f"from {_VENV_DEPENDENCY} import VERSION\n\nMARKER = VERSION\n", encoding="utf-8"
    )
    point = _point(_ZETA)
    with pytest.raises(ModuleNotFoundError):
        point.load()
    extend(home)
    assert point.load() == "9.9.9"

def test_discovery_puts_the_workspace_on_the_path_before_it_hands_back_a_single_point(
    tmp_path: Path,
) -> None:
    """Where the insertion is wired, asserted rather than left to a reading of `registry.py`.

    `discovered` is the one function that turns a workspace into entry points, so a point that
    exists and a workspace that is importable are one event and no caller has to order them.
    """
    home = _home(tmp_path)
    _workflow(home, _ALPHA, "alpha")
    assert str(workflows_dir(home)) not in sys.path
    found = discovered(home)
    assert [point.name for point in found.points] == [_ALPHA]
    assert str(workflows_dir(home)) in sys.path

# --- the file the venv gets, which no run of AGL reads -------------------------------------------

def _pth(home: AglHome) -> Path:
    """Where the writer puts its file, composed at the segment this interpreter installs into."""
    return workspace_editor_pth(home, _segment())

def _holding_agl() -> str:
    """The directory the `agl` package this process imported sits in - `src/` in this checkout.

    Read off `agl` itself rather than off `Path(__file__)`, which is what `src/` composes it from:
    a writer that named its own tree by a different route would agree with a test that used the
    same route and with nothing else.
    """
    assert agl.__file__ is not None, "`agl` was imported from something that is not a file"
    return str(Path(agl.__file__).parent.parent)

def test_the_file_written_into_the_venv_names_the_directory_the_running_agl_imports_from(
    tmp_path: Path,
) -> None:
    """One line, and it is the directory an editor has to be told about to resolve `agl.sdk`.

    `agl new` scaffolds a workflow whose first line is `from agl.sdk import Run, workflow`, and the
    venv `agl sync` builds installs everything that workflow declares except AGL itself - nothing
    declares it, and this is the deliberate half of that. So the file is what an editor pointed at
    the workspace venv reads `agl` through, and the trailing newline is there because `site` reads
    a `.pth` a line at a time.
    """
    home = _home(tmp_path)
    _venv(home)

    write_editor_pth(home)

    assert _pth(home).read_text(encoding="utf-8") == f"{_holding_agl()}\n"

def test_writing_the_path_file_puts_nothing_on_this_processs_import_path(tmp_path: Path) -> None:
    """The file is the editor's and the runtime's import path is `extend`'s, and they never meet.

    `sys.path.append` processes no `.pth` at all, so a run of AGL is unaffected by this file's
    contents, its absence, and anything stale in it. That is what makes an unwritable one something
    to pass over rather than to refuse a finished sync for.
    """
    home = _home(tmp_path)
    _venv(home)
    before = list(sys.path)

    write_editor_pth(home)

    assert sys.path == before

def test_writing_the_path_file_twice_leaves_one_file_holding_exactly_one_line(
    tmp_path: Path,
) -> None:
    """`agl sync` is run repeatedly, and a writer that appended would grow the file every time."""
    home = _home(tmp_path)
    site = _venv(home)

    write_editor_pth(home)
    write_editor_pth(home)

    assert [path.name for path in site.iterdir()] == [_pth(home).name]
    assert _pth(home).read_text(encoding="utf-8").splitlines() == [_holding_agl()]

def test_a_path_file_naming_an_agl_that_moved_is_replaced_rather_than_left_alone(
    tmp_path: Path,
) -> None:
    """The line is an absolute path, so a stale one is a directory that may not exist any more.

    An AGL reinstalled somewhere else leaves exactly this: a workspace whose venv still names the
    checkout it was synced from. Rewriting on every sync is the whole of the fix, which is why the
    writer compares the bytes rather than the file's existence.
    """
    home = _home(tmp_path)
    _venv(home)
    _pth(home).write_text("/somewhere/an/older/agl/was\n", encoding="utf-8")

    write_editor_pth(home)

    assert _pth(home).read_text(encoding="utf-8") == f"{_holding_agl()}\n"

def test_a_workspace_with_no_venv_beside_it_gains_no_path_file_at_all(tmp_path: Path) -> None:
    """`extend`'s absent-venv case from the writing side, and no directory is made to fill it.

    A venv is uv's to build and AGL creates none - a `site-packages` this function made would be
    one no interpreter had ever installed into, sitting where `extend` then looks for one.
    """
    home = _home(tmp_path)
    workflows_dir(home).mkdir(parents=True)

    write_editor_pth(home)

    assert [path.name for path in workspace_dir(home).iterdir()] == [workflows_dir(home).name]

def test_a_venv_built_by_another_interpreter_gains_no_path_file_of_this_ones(
    tmp_path: Path,
) -> None:
    """The segment is this interpreter's, so another interpreter's venv is a directory not there.

    `adapters/uv/syncer.py` passes `sys.executable`, so the two agree in practice; what this pins
    is that a disagreement writes nothing rather than writing into a venv nothing here will read.
    """
    home = _home(tmp_path)
    stale = workspace_site_packages(home, "python0.1")
    stale.mkdir(parents=True)

    write_editor_pth(home)

    assert list(stale.iterdir()) == []

def test_a_path_file_that_cannot_be_written_is_passed_over_without_a_raise(tmp_path: Path) -> None:
    """A finished install is a finished sync, and this file is not part of what was installed.

    A directory standing where the file goes rather than a `chmod`, which does nothing as root -
    the same substitution `tests/config/test_toml_file.py` makes for the same reason. What it
    provokes is an `OSError` on the write, which is every way this can fail on a real machine.
    """
    home = _home(tmp_path)
    _venv(home)
    _pth(home).mkdir()

    write_editor_pth(home)

    assert _pth(home).is_dir()

# --- the guard that keeps all of the above from contaminating the rest of the suite --------------

def test_no_test_in_this_session_has_left_a_temporary_directory_on_the_import_path(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """`tests/conftest.py`'s restore, measured from the outside rather than trusted.

    Every workspace any test builds lives under pytest's own temporary base, so an entry inside
    that base is a leak whichever test left it - and a leaked entry is what makes a suite pass or
    fail on the order it collected in. It reaches only the tests that ran before this one, which is
    a real limit and still the difference between a guard nobody measures and one that is.
    """
    base = str(tmp_path_factory.getbasetemp().parent)
    left = [entry for entry in sys.path if entry.startswith(base)]
    assert not left, (
        f"these entries under pytest's temporary root are still on `sys.path`: {left}. Something "
        f"extended the path and it was not taken back off - `_sys_path_as_each_test_found_it` in "
        f"tests/conftest.py is what should have, and every test after the one that leaked can now "
        f"import out of a directory pytest is about to delete"
    )
