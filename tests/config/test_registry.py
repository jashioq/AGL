"""Discovery driven by `EntryPoint` values the test constructs, plus one look at the real group.

`EntryPoint` is a public, constructible type - `EntryPoint(name, value, group)` and nothing else -
so every branch of the pure core is reachable without installing a package, building a
distribution, or arranging `sys.path`. That is the whole reason `names` and `load` take the entry
points as an argument, and this file is what that split was for.

The values point at this module's own objects - a stand-in workflow, a string for the load that
succeeds into the wrong type - and at one module path that does not exist. Nothing here writes a
package or a `.dist-info` directory: an entry point is a name, a `module:attr` string and a group,
and resolving it is the interpreter's job rather than this file's.

## Nothing here reads the real group any more, and that is a deletion rather than a gap

There used to be one impure test: it read `pyproject.toml`'s `agl.workflows` table, compared it
against what this environment's installed distribution contributes to that group, and then asserted
the group held `fix` and `split`. **AGL now ships no workflow and declares no table**, so both
halves are about nothing - the comparison is between two empty lists, and the membership check has
no member to look for.

What went with it is worth naming, because it was the only thing in this suite that could fail for
a reason outside the repository. `entry_points.txt` is a *build artifact*: an edit to
`pyproject.toml` is invisible until the next `uv pip install -e . --no-deps`, so between the two
the group this environment reports and the group this repository declares are two different lists.
That test diagnosed the drift by name, with the command that ends it, before saying anything about
which workflows were registered - because a reader told "`fix` is missing from the group" goes
looking in `agl/workflows/` for a package that is sitting right there. **Nothing diagnoses that
now.** It costs nothing while the table is empty, and the moment a workflow is registered anywhere
again - by AGL or by a distribution installed beside it - a test of this shape is what keeps a stale
install from being read as a workflow that failed to register.

Refusals are asserted on their class *and* on the name, the entry-point value or the list of
alternatives appearing in the message: "it raised" is satisfied by a refusal that leaves the
operator with nothing to do next.

## The second half of this file reads directories, and it still writes no distribution

`discovered` is where the entry points now come from: a walk of `workspace/workflows/` under
AGL_HOME, one `pyproject.toml` read per directory, one `EntryPoint` synthesised per line of that
file's entry-point table. The cases below build those directories under `tmp_path` and never under
the operator's own home - `AglHome` is constructed here rather than resolved, so no assertion in
this file depends on an environment variable or on what is installed anywhere.

What is still not built is a distribution. A synthesised point's `.dist` is `None` and nothing in
`src/agl` reads it, so a hand-written TOML table and an installed package produce the same type and
the same `load()`. The one case that proves it points its value at *this module*, which is already
importable, so that the claim being tested is the synthesis and not a `sys.path` insertion made
somewhere else.

**One bad directory may not answer for the others.** `agl workflows` exists to say what is there,
and a listing that collapses to nothing because one project file will not parse is the worst
possible answer to that question - the directory the operator is looking at is the one that
vanishes. So a directory that cannot be read into entry points comes back in `Discovery.broken`,
under the only name it has left, which is its own; and the assertions below pin both halves at once,
because "the broken one is reported" and "the others are still listed" are one claim.

## `check_unbroken` resolves a name against those directories, and the declaration wins

A directory's name is the only handle a broken one has, so an operator who types it gets that
directory's reason rather than `load`'s "no workflow by that name" - which would send them looking
for a workflow they have not written rather than at the file they have. What that name is *not* is
a declaration, and the case below named
`test_a_workflows_name_is_the_key_it_declares_and_not_the_directory_name` is that rule. It decides
the collision `_index` cannot see: two entry points of one name are two workflows and are refused,
while a broken directory sharing a declared name is one workflow beside a directory that declares
nothing at all - so the workflow runs, and the directory is still reported by the listing.
"""

from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Final
import pytest
from agl.config.distribution import DISTRIBUTION, installed_version
from agl.config.registry import (
    GROUP,
    Discovery,
    check_satisfied,
    check_unbroken,
    declarations,
    discovered,
    load,
    names,
)
from agl.config.toml_file import read_document
from agl.ports.errors import ConflictError, InputError, NotFoundError
from agl.ports.home_layout import AglHome, workflows_dir

# What a registered workflow looks like from here: a name, a `module:attr` value, and the group.
# The targets are real objects in this repository, so a load that is supposed to succeed does.
# Both names are invented. Nothing in this file resolves a name against what is registered anywhere,
# which is why one of them could go on reading `split` for a while after that workflow was deleted.
_WORKFLOW: Final = "tickets"
_OTHER: Final = "triage"

def _point(name: str, value: str) -> EntryPoint:
    return EntryPoint(name=name, value=value, group=GROUP)

class _Workflow:
    """Stands in for the type `api.py` passes as `load`'s `kind`. Any class does - that is why."""

def _loadable(name: str) -> EntryPoint:
    """An entry point resolving to something this module can be asked to narrow to `_Workflow`."""
    return _point(name, f"{__name__}:_instance")

# The two objects the entry points below resolve to. Module level, because `EntryPoint.load`
# imports a module and reads a dotted attribute path in it - it cannot see a local.
_instance = _Workflow()
_not_a_workflow = "a workflow name is not a workflow"

# --- listing -----------------------------------------------------------------------------------

def test_names_lists_every_registered_workflow_sorted() -> None:
    """Sorted, so `agl workflows` prints the same list on two machines that scanned differently.

    Three names, handed over in reverse of the order asserted, so a `names` that returned its input
    unchanged fails here. All three are invented. Two of them read `noop` and `split` until those
    workflows were deleted, and neither deletion cost this case anything - which is the point worth
    leaving behind: nothing in this half resolves a name, so what is registered anywhere is not a
    fact any assertion here rests on.
    """
    points = (_loadable(_WORKFLOW), _loadable(_OTHER), _loadable("backlog"))
    assert names(points) == ("backlog", "tickets", "triage")

def test_names_of_an_empty_group_is_empty() -> None:
    assert names(()) == ()

def test_names_imports_nothing_so_a_broken_workflow_is_still_listed() -> None:
    """One package that will not import must not take down the command that lists what is there."""
    points = (_loadable(_WORKFLOW), _point("broken", "agl.no.such.module:anything"))
    assert names(points) == ("broken", "tickets")

# --- loading, and the narrowing that keeps `Any` out of the caller -----------------------------

def test_load_returns_the_registered_object_narrowed_to_the_expected_type() -> None:
    loaded = load((_loadable(_WORKFLOW),), _WORKFLOW, _Workflow)
    assert loaded is _instance

def test_load_picks_the_named_entry_point_out_of_several() -> None:
    points = (_loadable(_OTHER), _loadable(_WORKFLOW))
    assert load(points, _WORKFLOW, _Workflow) is _instance

# --- a name in no entry point: NotFoundError, exit 3 -------------------------------------------

def test_an_unknown_name_is_not_found_and_the_message_lists_what_is_registered() -> None:
    points = (_loadable(_WORKFLOW), _loadable(_OTHER))
    with pytest.raises(NotFoundError) as raised:
        load(points, "tickest", _Workflow)
    message = str(raised.value)
    assert "tickest" in message
    assert _WORKFLOW in message
    assert _OTHER in message

def test_an_unknown_name_in_an_empty_registry_says_no_workflow_is_declared_at_all() -> None:
    """A different situation from "not that one", and a refusal ending in an empty list is a bug.

    Nothing declared is not the same answer as nothing installed, and the refusal has to hand the
    operator somewhere to go: the group it read, the command that writes a workflow, and the
    command that spells out how to declare one by hand. `agl new` is asserted as text here rather
    than against `cli/commands/new.py`'s own `NAME`, because a test of the registry has no business
    importing the CLI; `tests/cli/test_workflows_command.py` is where that name is pinned to the
    module declaring it.
    """
    with pytest.raises(NotFoundError) as raised:
        load((), _WORKFLOW, _Workflow)
    message = str(raised.value)
    assert "no workflow is declared at all" in message
    assert GROUP in message
    assert "agl new" in message
    assert "agl workflows" in message

# --- one name, two declarations: ConflictError, exit 4 -----------------------------------------

def test_two_declarations_of_one_name_are_refused_on_load_naming_both_values() -> None:
    """Both values, because they are the whole of what the refusal can be specific about.

    An `EntryPoint` carries a name, a value and a group and no path, so the two directories the
    declarations were read from are not something `_index` could name even if it wanted to. What it
    has is the two `<module>:<attribute>` strings, and a refusal that printed one of them would
    leave the operator hunting the other. `pyproject.toml` is asserted because the fix is an edit
    to a file: a message that only said the name was ambiguous would satisfy the two above.
    """
    held = _loadable(_WORKFLOW)
    points = (held, _point(_WORKFLOW, "somewhere.else:tickets"))
    with pytest.raises(ConflictError) as raised:
        load(points, _WORKFLOW, _Workflow)
    message = str(raised.value)
    assert _WORKFLOW in message
    assert held.value in message
    assert "somewhere.else:tickets" in message
    assert "pyproject.toml" in message

def test_two_declarations_of_one_name_are_refused_while_listing_and_not_only_on_load() -> None:
    """The refusal is raised while indexing, so `agl workflows` refuses rather than printing one
    row for two workflows and letting the operator pick blind."""
    points = (_loadable(_WORKFLOW), _point(_WORKFLOW, "somewhere.else:tickets"))
    with pytest.raises(ConflictError):
        names(points)

# --- a declaration that does not hold up: InputError, exit 2 -----------------------------------

def test_an_entry_point_whose_module_is_missing_is_refused_with_the_original_chained() -> None:
    value = "agl.no.such.module:anything"
    with pytest.raises(InputError) as raised:
        load((_point(_WORKFLOW, value),), _WORKFLOW, _Workflow)
    assert value in str(raised.value)
    assert _WORKFLOW in str(raised.value)
    # The workflow author debugging their own package needs the real traceback, not a sentence
    # saying one happened.
    assert isinstance(raised.value.__cause__, ModuleNotFoundError)

def test_an_entry_point_whose_attribute_is_missing_is_refused_with_the_original_chained() -> None:
    value = f"{__name__}:_no_such_attribute"
    with pytest.raises(InputError) as raised:
        load((_point(_WORKFLOW, value),), _WORKFLOW, _Workflow)
    assert value in str(raised.value)
    assert isinstance(raised.value.__cause__, AttributeError)

def test_an_entry_point_that_loads_the_wrong_kind_of_object_is_refused() -> None:
    """It imported fine and resolved to something. Being the wrong type is the remaining failure."""
    value = f"{__name__}:_not_a_workflow"
    with pytest.raises(InputError) as raised:
        load((_point(_WORKFLOW, value),), _WORKFLOW, _Workflow)
    message = str(raised.value)
    assert value in message
    assert _Workflow.__qualname__ in message
    assert "str" in message

# --- the workspace scan: directories on disk, and one bad one that answers only for itself -------

def _home(tmp_path: Path) -> AglHome:
    """An AGL_HOME nothing else can reach, built rather than resolved so no variable is read."""
    return AglHome(tmp_path / "home")

def _directory(home: AglHome, named: str, pyproject: str | None = None) -> Path:
    """One directory under `workspace/workflows/`, holding the project file it is given, if any."""
    path = workflows_dir(home) / named
    path.mkdir(parents=True)
    if pyproject is not None:
        (path / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    return path

def _declaring(*declarations: str) -> str:
    """A project file whose entry-point table holds exactly the lines it was handed."""
    head = f'[project]\nname = "probe"\nversion = "0.1.0"\n\n[project.entry-points."{GROUP}"]\n'
    return head + "".join(f"{line}\n" for line in declarations)

def _pointing_here(named: str) -> str:
    """A declaration whose value resolves to this module, so nothing has to reach `sys.path`."""
    return f'{named} = "{__name__}:_instance"'

def test_a_workspace_directory_declaring_one_workflow_yields_that_one_entry_point(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path)
    _directory(home, "triage", _declaring(_pointing_here("triage")))
    found = discovered(home)
    assert found.broken == ()
    assert [(point.name, point.value, point.group) for point in found.points] == [
        ("triage", f"{__name__}:_instance", GROUP)
    ]

def test_a_synthesised_entry_point_loads_the_object_its_own_declaration_names(
    tmp_path: Path,
) -> None:
    """The whole of what synthesising one buys: it resolves exactly as an installed one does.

    The declared value names this module, which is importable already, so the assertion is about
    the point built out of a TOML table and not about anything on `sys.path`.
    """
    home = _home(tmp_path)
    _directory(home, "triage", _declaring(_pointing_here("triage")))
    (point,) = discovered(home).points
    assert point.load() is _instance

def test_two_declarations_in_one_directory_both_arrive_as_workflows_of_the_group(
    tmp_path: Path,
) -> None:
    """A directory is one project file and not one workflow, so the table may hold several."""
    home = _home(tmp_path)
    _directory(
        home, "triage", _declaring(_pointing_here(_WORKFLOW), _pointing_here(_OTHER))
    )
    assert names(discovered(home).points) == (_WORKFLOW, _OTHER)

def test_a_workflows_name_is_the_key_it_declares_and_not_the_directory_name(
    tmp_path: Path,
) -> None:
    """What `agl run` takes is the left-hand side of the declaration, wherever the file sits."""
    home = _home(tmp_path)
    _directory(home, "a-directory-called-something-else", _declaring(_pointing_here(_OTHER)))
    assert names(discovered(home).points) == (_OTHER,)

def test_a_missing_workflows_directory_is_a_quiet_empty_answer_and_not_an_error(
    tmp_path: Path,
) -> None:
    """No workspace is the ordinary state of a fresh install, and the walk makes none to find."""
    assert discovered(_home(tmp_path)) == Discovery((), ())

def test_a_directory_holding_no_project_file_is_stray_and_is_left_out_entirely(
    tmp_path: Path,
) -> None:
    """The workspace is the operator's own directory: what makes a claim is a project file."""
    home = _home(tmp_path)
    _directory(home, "notes")
    _directory(home, "triage", _declaring(_pointing_here("triage")))
    found = discovered(home)
    assert found.broken == ()
    assert names(found.points) == ("triage",)

def test_a_file_lying_beside_the_workflow_directories_is_not_scanned_as_one(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path)
    _directory(home, "triage", _declaring(_pointing_here("triage")))
    (workflows_dir(home) / "README.md").write_text("what is in here\n", encoding="utf-8")
    found = discovered(home)
    assert found.broken == ()
    assert names(found.points) == ("triage",)

def test_one_unparseable_project_file_never_stops_the_other_directories_being_listed(
    tmp_path: Path,
) -> None:
    """The claim `agl workflows` rests on: one broken directory answers for itself and no other."""
    home = _home(tmp_path)
    _directory(home, "half-written", '[project\nname = "oops"\n')
    _directory(home, "triage", _declaring(_pointing_here("triage")))
    found = discovered(home)
    assert names(found.points) == ("triage",)
    assert [entry.directory for entry in found.broken] == ["half-written"]

def test_a_broken_directory_keeps_its_own_name_and_carries_the_path_that_failed(
    tmp_path: Path,
) -> None:
    """Its directory is the only name it has, and the reason has to say which file to open."""
    home = _home(tmp_path)
    path = _directory(home, "triage", "[project\n") / "pyproject.toml"
    (entry,) = discovered(home).broken
    assert entry.directory == "triage"
    assert str(path) in entry.reason

def test_a_project_file_that_is_a_directory_is_broken_rather_than_a_failed_listing(
    tmp_path: Path,
) -> None:
    """Every way of not having a readable file but absence lands on one directory, not the walk."""
    home = _home(tmp_path)
    (workflows_dir(home) / "triage" / "pyproject.toml").mkdir(parents=True)
    _directory(home, "other", _declaring(_pointing_here("other")))
    found = discovered(home)
    assert names(found.points) == ("other",)
    assert [entry.directory for entry in found.broken] == ["triage"]

def test_a_project_file_declaring_no_workflow_table_is_reported_rather_than_skipped(
    tmp_path: Path,
) -> None:
    """A directory here is a workflow somebody is writing, so the missing table is the mistake."""
    home = _home(tmp_path)
    _directory(home, "triage", '[project]\nname = "triage"\nversion = "0.1.0"\n')
    (entry,) = discovered(home).broken
    assert entry.directory == "triage"
    assert GROUP in entry.reason

def test_a_table_under_a_different_entry_point_group_declares_no_workflow_here(
    tmp_path: Path,
) -> None:
    """The group is matched exactly: a console script is a declaration about something else."""
    home = _home(tmp_path)
    _directory(
        home,
        "triage",
        '[project]\nname = "triage"\nversion = "0.1.0"\n\n'
        '[project.entry-points."console_scripts"]\ntriage = "triage:main"\n',
    )
    found = discovered(home)
    assert found.points == ()
    assert [entry.directory for entry in found.broken] == ["triage"]

def test_an_entry_point_value_that_is_not_a_string_makes_its_directory_broken(
    tmp_path: Path,
) -> None:
    """Refused where it is written rather than at the import that would fail unreadably."""
    home = _home(tmp_path)
    _directory(home, "triage", _declaring("triage = 3"))
    (entry,) = discovered(home).broken
    assert entry.directory == "triage"
    assert "triage" in entry.reason

def test_broken_directories_come_back_in_directory_order_whatever_the_filesystem_says(
    tmp_path: Path,
) -> None:
    """Sorted for `names`' own reason: two machines that walked differently print one listing."""
    home = _home(tmp_path)
    for named in ("gamma", "alpha", "beta"):
        _directory(home, named, "[project\n")
    assert [entry.directory for entry in discovered(home).broken] == ["alpha", "beta", "gamma"]

# --- resolving a name against the directories that broke -----------------------------------------

def test_a_name_only_a_broken_directory_carries_is_refused_with_that_directorys_reason(
    tmp_path: Path,
) -> None:
    """What `agl run <a directory being written>` gets: the file to open, not a shopping list."""
    home = _home(tmp_path)
    path = _directory(home, "half-written", "[project\n") / "pyproject.toml"
    with pytest.raises(InputError) as raised:
        check_unbroken(discovered(home), "half-written")
    assert str(path) in str(raised.value)

def test_a_name_no_broken_directory_carries_is_left_for_the_load_to_answer_for(
    tmp_path: Path,
) -> None:
    """The check is silent on everything else, so an unknown name still gets `load`'s listing."""
    home = _home(tmp_path)
    _directory(home, "half-written", "[project\n")
    _directory(home, "triage", _declaring(_pointing_here(_OTHER)))
    found = discovered(home)
    check_unbroken(found, _WORKFLOW)
    with pytest.raises(NotFoundError):
        load(found.points, _WORKFLOW, _Workflow)

def test_a_declared_name_is_never_refused_for_a_broken_directory_that_shares_it(
    tmp_path: Path,
) -> None:
    """The collision `_index` cannot see, decided by the rule that a directory declares nothing.

    The workflow is declared under `triage` from a directory called something else, and the
    directory called `triage` is the broken one. Two *points* of one name are two workflows and
    `ConflictError` is right for them; this is one workflow beside a directory that named no
    workflow at all, so refusing would cost the operator a workflow that works.
    """
    home = _home(tmp_path)
    _directory(home, "elsewhere", _declaring(_pointing_here(_OTHER)))
    _directory(home, _OTHER, "[project\n")
    found = discovered(home)
    check_unbroken(found, _OTHER)
    assert load(found.points, _OTHER, _Workflow) is _instance

# --- the AGL a workflow declares it was written against, read in the same pass ------------------
#
# The walk already opens each directory's project file for the entry-point table, and it reads the
# `[tool.agl] requires` value out of that same document. What it is looking for is one string: a
# bound on AGL's own distribution, which `agl new` writes naming the AGL that scaffolded the
# workflow. `config/distribution.py` owns the comparison and every shape that is *not* a refusal -
# no bound, an unparseable one, another distribution's, an AGL with no version of its own - and
# `tests/config/test_distribution.py` is where those are asserted, one per case, with no directory
# involved. What is left here is the half only a walk can show.
#
# **The order is the deliverable.** `load` is the line that imports a workflow's module, and a
# workflow written against a newer AGL fails that import on whichever name moved - inside the
# operator's own file, naming a symbol rather than a version. So every case below points its
# declaration at a module that does not exist and cannot be made to: what the refusal says is then
# the whole evidence of which of the two ran first.
#
# **An unmet bound is not a broken directory**, and the two are deliberately different fields. A
# broken directory declared no workflow, so it has no name but its own and drops out of the
# listing; this one declared a perfectly good workflow that this AGL cannot run, so it keeps its
# name and `agl workflows` still prints it - which is that command's own promise, that a workflow
# whose code will not load is still a workflow the workspace declares.

_UNIMPORTABLE: Final = "a_module_no_workspace_holds:anything"

_BEYOND_REACH: Final = "99999.0.0"

def _needing(bound: str, *declarations: str) -> str:
    """A project file needing AGL at `bound`, declaring whichever entry points it is handed."""
    return (
        f'[project]\nname = "probe"\nversion = "0.1.0"\n\n'
        f'[project.entry-points."{GROUP}"]\n'
        + "".join(f"{line}\n" for line in declarations)
        + f'\n[tool.agl]\nrequires = "{DISTRIBUTION}{bound}"\n'
    )

def test_a_workflow_needing_an_agl_this_is_not_is_refused_before_anything_is_imported(
    tmp_path: Path,
) -> None:
    """The deliverable, and the two refusals are compared rather than one of them asserted alone.

    The declaration points at a module nothing anywhere holds, so `load` has exactly one thing it
    can do with these points and it is not what the operator should read. Both calls are made, in
    both orders, off one walk: the check answers about the bound, the load answers about an import
    that failed, and `api._loaded` asks them in the order that gives the first. Without the second
    call this test would pass against a check that fired for no reason at all.
    """
    home = _home(tmp_path)
    _directory(home, "triage", _needing(f">={_BEYOND_REACH}", f"triage = {_UNIMPORTABLE!r}"))
    found = discovered(home)

    with pytest.raises(InputError) as refused:
        check_satisfied(found, "triage")
    with pytest.raises(InputError) as imported:
        load(found.points, "triage", _Workflow)

    assert _BEYOND_REACH in str(refused.value)
    assert "loading it failed" in str(imported.value)
    assert "loading it failed" not in str(refused.value)

def test_the_refusal_names_the_bound_the_file_declared_and_the_agl_that_is_running(
    tmp_path: Path,
) -> None:
    """Both numbers, because either alone leaves the operator with nothing to decide.

    The bound says which AGL the workflow was written against and the running version says which
    one is here; a message carrying one of them tells somebody that something is wrong and not
    what. The file is named too, that being where the line they would edit sits.
    """
    home = _home(tmp_path)
    path = _directory(
        home, "triage", _needing(f">={_BEYOND_REACH}", f"triage = {_UNIMPORTABLE!r}")
    ) / "pyproject.toml"

    with pytest.raises(InputError) as refused:
        check_satisfied(discovered(home), "triage")

    said = str(refused.value)
    assert f">={_BEYOND_REACH}" in said
    assert installed_version() in said
    assert str(path) in said

def test_a_workflow_out_of_bound_keeps_its_name_and_is_no_broken_directory(
    tmp_path: Path,
) -> None:
    """`agl workflows` prints what a workspace declares, and this workflow is declared.

    A directory in `broken` declared no workflow and is reported under its own name because that is
    the only name it has left. This one declared a name and `agl run` takes it - the refusal is
    about the AGL underneath rather than about the file - so dropping it from the listing would
    hide the workflow whose bound the operator has to go and read.
    """
    home = _home(tmp_path)
    _directory(home, "triage", _needing(f">={_BEYOND_REACH}", f"triage = {_UNIMPORTABLE!r}"))

    found = discovered(home)

    assert names(found.points) == ("triage",)
    assert found.broken == ()
    assert sorted(found.unsatisfied) == ["triage"]

def test_a_workflow_whose_bound_this_agl_meets_reaches_the_load_as_usual(
    tmp_path: Path,
) -> None:
    """The control, and it is what keeps the check from being a refusal of every workflow.

    The bound is composed from the version this AGL reports, so it is met on any tree that can run
    this test at all. The load is then reached and answers about the import, which is the sentence
    the case above proves is *not* what an out-of-bound workflow gets.
    """
    home = _home(tmp_path)
    _directory(
        home, "triage", _needing(f">={installed_version()}", f"triage = {_UNIMPORTABLE!r}")
    )
    found = discovered(home)

    check_satisfied(found, "triage")

    assert found.unsatisfied == {}
    with pytest.raises(InputError) as imported:
        load(found.points, "triage", _Workflow)
    assert "loading it failed" in str(imported.value)

def test_one_directorys_unmet_bound_leaves_every_other_workflow_in_the_workspace_alone(
    tmp_path: Path,
) -> None:
    """A bound is one workflow's claim about AGL and answers for that workflow and no other.

    The same rule a broken directory follows, and it has to be said again here because the field is
    different: an operator with five workflows and one written against tomorrow's AGL still runs
    the other four. The one that is fine is loaded rather than merely listed, which is the half a
    listing assertion alone would not reach.
    """
    home = _home(tmp_path)
    _directory(home, "triage", _needing(f">={_BEYOND_REACH}", f"triage = {_UNIMPORTABLE!r}"))
    _directory(home, "tickets", _declaring(_pointing_here(_WORKFLOW)))
    found = discovered(home)

    check_satisfied(found, _WORKFLOW)

    assert names(found.points) == ("tickets", "triage")
    assert sorted(found.unsatisfied) == ["triage"]
    assert load(found.points, _WORKFLOW, _Workflow) is _instance

def test_the_check_is_silent_about_a_name_no_directory_in_the_workspace_declared(
    tmp_path: Path,
) -> None:
    """Like `check_unbroken` beside it: silent on everything it has nothing to say about.

    An unknown name is `load`'s to answer, with its listing of what is declared. A check that
    refused here would take that listing away from the operator and put a message about a bound in
    its place, about a workflow that does not exist.
    """
    home = _home(tmp_path)
    _directory(home, "triage", _needing(f">={_BEYOND_REACH}", f"triage = {_UNIMPORTABLE!r}"))
    found = discovered(home)

    check_satisfied(found, _WORKFLOW)

    with pytest.raises(NotFoundError):
        load(found.points, _WORKFLOW, _Workflow)

# --- an import that failed, and which of two things was missing ---------------------------------
#
# `load` is the one line that imports, and what it catches covers two situations an operator fixes
# in different files. A workflow whose own module or attribute is not there is a declaration
# pointing at nothing, and the fix is inside that directory. A workflow that imported something
# else and did not find it is a dependency nothing installed, and the fix is a line in that
# directory's `[project] dependencies` followed by an install - a different sentence, so the two
# are told apart rather than sharing one.
#
# **The cut is `ModuleNotFoundError` and not `ImportError`**, because only the first means no
# finder answered at all: `from agl.sdk import gone` raises the plain class and is the workflow's
# own code failing against the AGL it has, which is not something an install would put right.
#
# Both cases below are driven through a real directory and a real import rather than through a
# hand-built error, because the branch reads `EntryPoint.module` against what the interpreter said
# was missing and a constructed error would let this file decide both halves.

_ABSENT_PACKAGE: Final = "a_package_no_environment_in_this_suite_provides"

_IMPORTING_WORKFLOW: Final = "probe_workflow_importing_something_absent"

def _importing(home: AglHome, named: str, absent: str) -> None:
    """A workflow directory whose package is importable and whose first line is not."""
    directory = _directory(home, named, _declaring(f'{named} = "{named}:{named}"'))
    (directory / "__init__.py").write_text(f"import {absent}\n", encoding="utf-8")

def test_a_module_the_workflow_imports_and_nothing_installed_is_refused_as_a_dependency(
    tmp_path: Path,
) -> None:
    """The deliverable: the name that was missing, and the file the operator declares it in.

    The workflow's own package imports fine - the directory is there, the walk found it, and
    `sys.path` reaches it - so the only thing missing is the package on its first line, which no
    install in this suite provides. What the refusal must not do is send the operator into their
    own module looking for a declaration that is not the problem.
    """
    home = _home(tmp_path)
    _importing(home, _IMPORTING_WORKFLOW, _ABSENT_PACKAGE)
    found = discovered(home)

    with pytest.raises(InputError) as refused:
        load(found.points, _IMPORTING_WORKFLOW, _Workflow)

    said = str(refused.value)
    assert _ABSENT_PACKAGE in said
    assert "not installed" in said
    assert "dependencies" in said

def test_the_workflows_own_missing_module_is_refused_about_the_declaration_and_not_a_dependency(
    tmp_path: Path,
) -> None:
    """The other half of the same branch, and the two are asserted against each other.

    Nothing is installable here: the declaration names a module that does not exist, so the fix is
    the line that names it and no `[project] dependencies` entry would change anything. A refusal
    offering an install would be the wrong file entirely - and without this case, a branch that
    never fired would pass the one above just as happily.
    """
    home = _home(tmp_path)
    _directory(home, "triage", _declaring(f"triage = {_UNIMPORTABLE!r}"))
    found = discovered(home)

    with pytest.raises(InputError) as refused:
        load(found.points, "triage", _Workflow)

    said = str(refused.value)
    assert "loading it failed" in said
    assert "not installed" not in said

# --- one directory's reading, handed a document somebody else parsed ----------------------------

@pytest.mark.parametrize(
    "document",
    [
        _declaring(_pointing_here("triage")),
        '[project]\nname = "triage"\nversion = "0.1.0"\n',
        _declaring("triage = 3"),
        _needing(f">={_BEYOND_REACH}", f"triage = {_UNIMPORTABLE!r}"),
    ],
)
def test_a_document_parsed_elsewhere_reads_exactly_as_the_walk_reads_it_off_disk(
    tmp_path: Path, document: str
) -> None:
    """`agl get` hands over a project file still in memory, and it is read as the walk reads it.

    The same four shapes the walk meets - declaring, declaring nothing, declaring a non-string and
    declaring past this AGL - and the whole `Discovery` compared, so a second reading drifting on
    any field of it fails here rather than as a download refused in other words than a listing.
    """
    home = _home(tmp_path)
    directory = _directory(home, "triage", document)
    parsed = read_document(directory / "pyproject.toml")
    assert parsed is not None

    assert declarations(directory, parsed) == discovered(home)
