"""`agl new <workflow>`: the on-ramp, the install that follows it, and the run that has to work.

This is the one command that writes a workflow, so its acceptance criterion is not a file listing:
it is that **`agl run <workflow>` works immediately afterwards**, against the workspace on disk and
against nothing this file arranged. That is the first test below and everything else here supports
it. A scaffold asserted by inspection - the right two filenames, the right table in the TOML - can
be wrong in every way that matters and still pass: a declaration naming a module that is not there,
a package Python reads as a namespace package, a workflow the framework loads and cannot call.

**`agl new` is no longer offline, and the poison it used to be measured under now measures
something better.** The command scaffolds and then installs what the workspace declares, so the
one door it deliberately leaves through is uv - and what the first test asserts is the *ordering*
that follows from it: the two documents are on disk before the installer is started, so an
installer that cannot start at all leaves a scaffold behind rather than half of one. The run that
follows it is still driven with both doors shut and a fake installer, which is where "the scaffold
runs at once" survives: the entry point comes off the file `agl new` wrote, through
`config/registry.py`'s walk of the workspace and `config/workspace_path.py`'s entry on `sys.path`,
with `container.fakes()` behind it so no credential exists to spend and an agent that raises if
anything asks it for a turn.
`tests/test_measurable_targets.py::test_every_declared_command_runs_on_fakes_with_no_way_out` is
where that poison is written out exhaustively, and it drives this command too; what is poisoned
here is kept local so that this file's central claim does not depend on reading another one.

**The installer is substituted through `main.Invocation`'s own `syncer` field**, which is the seam
`cli/main.py` declares for exactly this; its default is `container.real_syncer` and
`tests/cli/test_main.py` is where that default is pinned. Every invocation below hands one in, so
no test here starts uv except the one whose whole subject is that it could not be started.

**Nothing here reaches the operator's own home.** `AGL_HOME` is resolved from a mapping handed to
`sources.resolve_settings` and never from the process environment, and every path is under
`tmp_path` - which matters more for this suite than for any other, because these tests *create*
directories rather than read them.

**The one import of a written module is undone afterwards.** No other test in this repository
imports a module out of `tmp_path`: entry points elsewhere point at test modules that are already
importable. `sys.modules` is process-global and `tests/conftest.py` restores `sys.path` and not it,
so the module this suite imports is taken back out under its own name - otherwise the second test
to scaffold that name would silently run the first one's code out of a deleted directory.
"""

import ast
import asyncio
import inspect
import socket
import subprocess
import sys
import sysconfig
import tomllib
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Final, NoReturn
import pytest
import agl
from agl.adapters.uv.fake import FakeSyncer
from agl.cli import main
from agl.cli.commands import new as new_command
from agl.config import container, distribution, registry, sources
from agl.ports.agent import AgentTask
from agl.ports.errors import NotFoundError, UpstreamUnavailable
from agl.ports.home_layout import (
    AglHome,
    workflow_dir,
    workflow_module,
    workflow_pyproject,
    workflows_dir,
    workspace_dir,
    workspace_editor_pth,
    workspace_pyproject,
    workspace_site_packages,
)
from agl.ports.ids import ProjectName, WorkflowName
from agl.ports.sync import Syncer, SyncOutcome
from agl.ports.tree_layout import TreesRoot
from agl.sdk.params import RefusingParser
from agl.sdk.testing import Reply

# The name the acceptance test scaffolds, imports and runs. Distinctive because it becomes a
# top-level module in this interpreter for the length of one test.
SCAFFOLDED: Final = "scaffolded"

TRIAGE: Final = WorkflowName("triage")

PROJECT: Final = ProjectName("myapp")

# `agl init` is the one command that reads `cwd`, and no invocation below is one; the field is not
# optional (`cli/main.py` argues why), so it carries a real path nothing here opens.
ELSEWHERE: Final = Path("/nowhere")

AGREED: Final = SyncOutcome(synced=True, status=0, output="")

# The `lib/` subdirectory this interpreter installs into, which is the one a sync addresses:
# `adapters/uv/syncer.py` builds the venv for `sys.executable` and nothing else.
SEGMENT: Final = Path(sysconfig.get_path("purelib")).parent.name

class Recording(Syncer):
    """A syncer answering as scripted and keeping what it was asked, which `FakeSyncer` does not.

    `existed` is read at the moment the installer is called and not afterwards, because what it is
    there to say is that the workspace was already made by the time the sync was started.
    """

    def __init__(self, outcome: SyncOutcome = AGREED) -> None:
        self.asked: list[Path] = []
        self.existed: list[bool] = []
        self._outcome = outcome

    async def sync(self, workspace: Path) -> SyncOutcome:
        self.asked.append(workspace)
        self.existed.append(workspace.is_dir())
        return self._outcome

class Raising(Syncer):
    """A syncer that raises what an adapter raises, so `main`'s one table answers for the class."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    async def sync(self, workspace: Path) -> SyncOutcome:
        raise self._error

class WentOutside(BaseException):
    """What a poisoned door raises, and a `BaseException` for the reason target #8 gives its own.

    `main.main` catches `Exception` and answers with an exit status, so a command that went outside
    would arrive at the assertion as a number rather than as the door it went through.
    """

def _refusing(door: str) -> object:
    """A stand-in for `door` that raises rather than doing what it was for."""

    def poisoned(*args: object, **kwargs: object) -> NoReturn:
        raise WentOutside(f"a scaffold, its installer or its run reached {door}")

    return poisoned

def _poison(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both doors out of the interpreter, for the length of one test.

    `subprocess.Popen.__init__` rather than `subprocess.run`: every spawn the standard library
    makes constructs one in the end, asyncio's included, and the two asyncio spellings are poisoned
    by name as well because they are what the adapters actually write.

    `socket.socketpair` and `socket.socket.__init__` are deliberately left alone - asyncio's own
    self-pipe is a socket pair, so poisoning either breaks the event loop rather than the network.
    """
    monkeypatch.setattr(subprocess.Popen, "__init__", _refusing("subprocess.Popen"))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _refusing("create_subprocess_exec"))
    monkeypatch.setattr(asyncio, "create_subprocess_shell", _refusing("create_subprocess_shell"))
    monkeypatch.setattr(socket.socket, "connect", _refusing("socket.connect"))
    monkeypatch.setattr(socket, "create_connection", _refusing("socket.create_connection"))
    monkeypatch.setattr(socket, "getaddrinfo", _refusing("socket.getaddrinfo"))

def _unwanted(task: AgentTask) -> Reply:
    """An agent that fails the test if a run reaches it: a scaffold spends no turn and no money."""
    raise AssertionError(f"a scaffolded workflow asked {task.model} for a turn")

def _never() -> tuple[ProjectName, object]:
    """A `Registered` that fails the test if a command calls it: `agl new` takes no repository."""
    raise AssertionError("`agl new` composed a repository")

def _home(tmp_path: Path) -> AglHome:
    """An AGL_HOME under `tmp_path` that is not there yet - what a first `agl new` meets."""
    return AglHome(tmp_path / "home")

def _main(home: AglHome, *argv: str, syncer: Syncer | None = None) -> int:
    """One `agl` invocation reading `home`, with no repository behind it and no entry points.

    The installer defaults to `FakeSyncer` rather than to the field's own default, which would
    start uv on every invocation in this file: `agl new` installs what the workspace declares once
    the scaffold is written, and a test that scaffolds is not a test that wants an index.
    """
    installer = FakeSyncer() if syncer is None else syncer
    return main.main(
        argv,
        compose=lambda: main.Invocation(
            registered=_never,  # type: ignore[arg-type]
            settings=sources.resolve_settings(
                sources.Overrides(), {"AGL_HOME": str(home.path)}
            ),
            cwd=ELSEWHERE,
            points=None,
            syncer=lambda: installer,
        ),
    )

def _installed(home: AglHome) -> Path:
    """The venv uv would have built, stood up by hand: `FakeSyncer` starts no process at all."""
    workspace_site_packages(home, SEGMENT).mkdir(parents=True)
    return workspace_editor_pth(home, SEGMENT)

def _new_parser() -> RefusingParser:
    """The `new` subparser alone, built the way `main.parser()` builds it, for inspection."""
    root = RefusingParser(prog="agl", allow_abbrev=False)
    commands = root.add_subparsers(dest="command", required=True, parser_class=RefusingParser)
    return new_command.declare(commands)

@pytest.fixture
def _forgotten_afterwards() -> Iterator[None]:
    """The scaffolded module, out of `sys.modules` again once the test that imported it is done."""
    yield
    for held in [
        name for name in sys.modules if name == SCAFFOLDED or name.startswith(f"{SCAFFOLDED}.")
    ]:
        del sys.modules[held]

# --- the acceptance criterion -------------------------------------------------------------------

@pytest.mark.usefixtures("_forgotten_afterwards")
def test_the_scaffold_lands_when_the_installer_cannot_start_and_what_landed_runs_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The criterion, rewritten around the one door `agl new` now leaves through.

    **The scaffold is written before the installer is started, and the poison is what measures
    it.** `agl new` runs here with `container.real_syncer` behind it against a poisoned
    `create_subprocess_exec`, which is what an operator with no uv on their machine meets: the
    command cannot finish, and what this asserts is that the two documents are on disk anyway. The
    ordering is the whole of the property - a sync attempted first would leave a workflow the
    operator asked for and does not have, and running `agl new` again after installing uv would
    then be the only way to get it.

    **What landed then runs, and that half is unchanged.** Four things have to be true at once for
    the second invocation to answer 0, and no smaller test asserts their conjunction. The
    declaration `agl new` wrote has to name a module that exists; the directory has to be a package
    rather than a namespace package, or `<name>:<name>` resolves to a module with no such
    attribute; the object the declaration names has to be a `Workflow`, which is what
    `registry.load` type-checks; and the function has to be callable by the framework with the
    `Run` it builds. Every one of those is a way a scaffold looks right in a listing and will not
    run. It is driven with a fake installer, the doors still shut, so the run itself reaches
    nothing outside this process.

    **The poison is proved live before either invocation and not after them.** Without that this
    would pass identically if `monkeypatch` had done nothing, which is the failure mode a poisoning
    test has - and both halves above rest on it.

    **The agent raises.** `container.fakes()` already has no credential to spend, so what this adds
    is that no turn is *asked for*: a scaffold declaring a role would reach one through preflight
    or through `run.step`, and either is work the operator pays for before writing a line.
    """
    home = _home(tmp_path)
    fakes = container.fakes(
        TreesRoot(tmp_path / "trees"), files={"src/a.py": b"pass\n"}, agent=_unwanted
    )
    scaffolded = WorkflowName(SCAFFOLDED)

    def composing(syncer: Callable[[], Syncer]) -> main.Compose:
        return lambda: main.Invocation(
            registered=lambda: (PROJECT, fakes.services),
            settings=sources.resolve_settings(
                sources.Overrides(), {"AGL_HOME": str(home.path)}
            ),
            cwd=ELSEWHERE,
            points=None,
            syncer=syncer,
        )

    _poison(monkeypatch)
    with pytest.raises(WentOutside):
        subprocess.run(["true"], check=False)
    with pytest.raises(WentOutside):
        socket.create_connection(("127.0.0.1", 1))

    with pytest.raises(WentOutside):
        main.main(("new", SCAFFOLDED), compose=composing(container.real_syncer))

    assert workflow_module(home, scaffolded).is_file()
    assert workflow_pyproject(home, scaffolded).is_file()
    capsys.readouterr()

    assert (
        main.main(("run", SCAFFOLDED, "-n", "first"), compose=composing(container.fake_syncer)) == 0
    )
    assert "run 'first' finished" in capsys.readouterr().out

def test_the_name_agl_run_takes_is_the_key_the_written_declaration_puts_on_the_left(
    tmp_path: Path,
) -> None:
    """The listing, off the file `agl new` wrote and off nothing this test arranged.

    `agl run <workflow>` takes the key on the left of a declaration rather than the name of the
    directory holding it, so this is where the two are asserted to be the same word - and the empty
    `broken` says the walk read the file rather than skipping past it, which a name arriving from
    somewhere else would not distinguish.
    """
    home = _home(tmp_path)

    assert _main(home, "new", str(TRIAGE)) == 0

    found = registry.discovered(home)
    assert registry.names(found.points) == (str(TRIAGE),)
    assert found.broken == ()

# --- what it writes -----------------------------------------------------------------------------

def test_a_new_workflow_is_two_files_in_a_directory_and_the_workspace_around_it(
    tmp_path: Path,
) -> None:
    """The whole of what one invocation makes, listed rather than sampled, from an absent home.

    A sampled assertion passes just as happily against a command that also wrote a prompts
    directory nobody asked for, an example role, or a `config.toml`. The listing is what says the
    workspace's own two entries plus this workflow's three are all of it.
    """
    home = _home(tmp_path)

    assert _main(home, "new", str(TRIAGE)) == 0

    assert sorted(path.relative_to(home.path).as_posix() for path in home.path.rglob("*")) == [
        "workspace",
        "workspace/pyproject.toml",
        "workspace/workflows",
        "workspace/workflows/triage",
        "workspace/workflows/triage/__init__.py",
        "workspace/workflows/triage/pyproject.toml",
    ]

def test_the_written_project_file_declares_one_workflow_and_the_agl_bound_beside_it(
    tmp_path: Path,
) -> None:
    """The declaration read as TOML: the group, the key, and the `module:attribute` it points at.

    The value is asserted whole rather than by its halves, because the halves are the two ways the
    file is self-consistent and wrong: a module the directory does not hold, and an attribute the
    module does not bind. `<name>:<name>` is the one spelling where the directory, the package it
    is imported as and the function inside it are the same word, which is what lets `agl run`
    take the name somebody typed at `agl new`.

    Two top-level tables and no third: `[project]`, which declares the workflow, and `[tool]`,
    which carries the bound AGL reads back and nothing else reads at all. The listing is what says
    a scaffold grew nothing beyond those two.
    """
    home = _home(tmp_path)
    _main(home, "new", str(TRIAGE))

    document = tomllib.loads(workflow_pyproject(home, TRIAGE).read_text(encoding="utf-8"))

    assert document["project"]["entry-points"] == {registry.GROUP: {"triage": "triage:triage"}}
    assert document["project"]["name"] == "triage"
    assert sorted(document) == ["project", "tool"]

def test_agl_new_writes_a_bound_on_the_running_agl_that_the_reader_accepts(
    tmp_path: Path,
) -> None:
    """The scaffold says which AGL wrote it, and the very next command reads that back.

    `config/registry.py` refuses a workflow whose declared bound the running AGL does not meet, and
    it refuses it *before* importing anything - so a scaffold whose own bound did not admit the AGL
    that wrote it would be a workflow refused by the command that created it. The walk is what is
    asserted rather than the string, because the string is `api.new_workflow`'s composition and the
    walk is the thing that has to accept it.

    The version is asserted present as well. A bare `agents-gl` with no specifier would round-trip
    through the reader just as happily and would say nothing at all about which AGL is meant, which
    is the way this passes while being useless.

    The value is read at the path the writer writes it to, which is the one thing the walk beneath
    it cannot say: an unread bound is silence and not a refusal, so a writer and a reader that had
    drifted onto two different keys would leave `unsatisfied` empty for the wrong reason.
    """
    home = _home(tmp_path)

    assert _main(home, "new", str(TRIAGE)) == 0

    document = tomllib.loads(workflow_pyproject(home, TRIAGE).read_text(encoding="utf-8"))
    declared = document["tool"]["agl"]["requires"]
    assert declared == f"{distribution.DISTRIBUTION}>={distribution.installed_version()}"
    assert registry.discovered(home).unsatisfied == {}

def test_the_written_module_is_the_packages_own_so_the_declaration_can_resolve_at_all(
    tmp_path: Path,
) -> None:
    """`__init__.py` and not some other filename, and this is not a matter of style.

    Without it the directory is a namespace package: `import triage` still succeeds, so the failure
    is not an import error but `triage:triage` resolving to a module with no such attribute - and
    `sdk/roles.py`'s `prompt_file` refuses one outright, a namespace package's `__file__` being
    `None` and there being no directory for a relative prompt path to be relative to. What the
    parsed module binds is asserted beside the filename, because that is the half a name check
    would miss.
    """
    home = _home(tmp_path)
    _main(home, "new", str(TRIAGE))

    written = workflow_module(home, TRIAGE)
    bound = {
        node.name
        for node in ast.parse(written.read_text(encoding="utf-8")).body
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
    }

    assert written.name == "__init__.py"
    assert bound == {"triage"}

def test_a_second_workflow_joins_the_workspace_the_first_one_made(tmp_path: Path) -> None:
    """The workspace is created and never re-created, and two workflows are two directories.

    `api.new_workflow` calls `make_workspace` unconditionally, so the second invocation asks for a
    workspace that is already there; the file it would rewrite is edited first, and the bytes are
    the assertion, which is the only way a rewrite is told from a skip when the paths are identical
    either way. The operator owns that file once it exists, and a command that rewrote it on every
    invocation would be one interrupted write away from taking their own lines with it, every time
    it was run - the sync that now follows the scaffold reaches the same directory and must leave
    it alone for the same reason.
    """
    home = _home(tmp_path)
    _main(home, "new", str(TRIAGE))
    root = workspace_pyproject(home)
    root.write_text(root.read_text(encoding="utf-8") + "# an operator's line\n", encoding="utf-8")
    before = root.read_bytes()

    assert _main(home, "new", "release") == 0

    assert root.read_bytes() == before
    assert sorted(path.name for path in workflows_dir(home).iterdir()) == ["release", "triage"]
    assert registry.names(registry.discovered(home).points) == ("release", "triage")

# --- the install that follows the scaffold ------------------------------------------------------

def test_the_installer_is_handed_the_workspace_directory_and_not_its_project_file(
    tmp_path: Path,
) -> None:
    """`Syncer.sync` takes the directory, and uv walks *up* from whatever it is given.

    Handing it the `pyproject.toml` would be a path uv reads as a directory that is not there;
    handing it `workflows/` would resolve the first project file above it, which is the workspace
    root by luck rather than by intent. `adapters/uv/syncer.py` refuses a directory with no
    project file in it for the same family of reasons, and this is the caller's half of that.

    That directory is asserted to have been *there* when the installer was handed it, which is the
    other half: the scaffold makes the workspace, so an operator who has typed nothing else meets
    an install rather than the adapter's refusal about a workspace nobody made.
    """
    home = _home(tmp_path)
    assert not home.path.exists()
    syncer = Recording()

    assert _main(home, "new", str(TRIAGE), syncer=syncer) == 0

    assert syncer.asked == [workspace_dir(home)]
    assert syncer.existed == [True]

def test_a_finished_sync_leaves_the_workspace_venv_naming_the_agl_that_ran_it(
    tmp_path: Path,
) -> None:
    """The last step, and the reason it is here: nothing installs AGL into that venv.

    `agl new` writes a workflow whose first line imports `agl.sdk`, and neither the workspace root
    nor the scaffold declares AGL as a dependency - `tests/config/test_toml_file.py` holds that,
    and it is deliberate, AGL being on the import path rather than installed into it. So an editor
    with the workspace venv selected has every package the workflow declares and not the one it
    imports first, and this file is what closes that gap. It closes it for an editor alone:
    `config/workspace_path.py` says why no run of AGL reads it.
    """
    home = _home(tmp_path)
    _main(home, "new", str(TRIAGE))
    pth = _installed(home)

    assert _main(home, "new", "release") == 0

    assert agl.__file__ is not None
    assert pth.read_text(encoding="utf-8") == f"{Path(agl.__file__).parent.parent}\n"

def test_a_refused_sync_writes_no_path_file_into_the_venv_it_did_not_build(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The one step a refusal skips, and it is skipped because of what the file would claim.

    uv exiting non-zero is every failure at once - a resolution with no solution, an index that
    could not be reached, a package that would not build - and none of them says what is in that
    venv now. A file written into it would name this AGL beside an environment nothing finished
    installing into, so the two agree: nothing installed, nothing claimed.

    The command still succeeds, and that is the half worth having a test for. An environment stood
    here before this sync was started - the `agl new` above is what built it - so the refusal is a
    warning rather than a stop, and the `.pth` is skipped on the path that carries on and not only
    on the one that exits.
    """
    home = _home(tmp_path)
    _main(home, "new", str(TRIAGE))
    pth = _installed(home)
    syncer = Recording(SyncOutcome(synced=False, status=2, output="error: no solution found\n"))

    assert _main(home, "new", "release", syncer=syncer) == 0

    assert not pth.exists()
    assert "error: no solution found" in capsys.readouterr().err

def test_a_refused_sync_exits_six_and_leaves_the_scaffold_it_could_not_install_for(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """uv refusing with no environment to fall back on is an upstream failure, which is exit 6.

    There is nothing older here for a workflow to import - this home has never been synced - so
    carrying on would only move the failure to the first line of the first workflow that imports
    anything, where it would name a package rather than an install that never happened. A refusal
    over an environment that *does* stand is the other rule and is a warning; the test above holds
    that half, and the difference between the two is measured before uv is started rather than
    after, `uv sync` having built the venv before it resolved.

    The status uv gave is named as well as the text, because the two answer different questions: a
    script branches on AGL's 6 and a person reads uv's own words for what could not be resolved.
    The output leaves with the refusal rather than on stdout, so this command writes nothing to
    stdout at all on the path where nothing was installed.

    The scaffold is asserted present afterwards for the reason the first test in this file gives:
    it was written before the installer was started, so fixing whatever uv complained about and
    typing the command again is a refusal about a name that already exists rather than a second
    chance at getting the files.
    """
    home = _home(tmp_path)
    syncer = Recording(SyncOutcome(synced=False, status=2, output="error: no solution found\n"))

    assert _main(home, "new", str(TRIAGE), syncer=syncer) == 6

    captured = capsys.readouterr()
    assert "error: no solution found" in captured.err
    assert "uv exited 2" in captured.err
    assert captured.out == ""
    assert workflow_module(home, TRIAGE).is_file()

def test_an_installer_that_could_not_be_started_exits_six_saying_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`UpstreamUnavailable` -> 6, and the adapter's sentence arrives unreworded.

    That is the shape of "uv is not installed", which is the commonest way this fails on a machine
    that has never run it: `adapters/uv/syncer.py` writes the sentence where the facts are - the
    binary it looked for, and three ways to install one - and nothing on the way up edits it.
    """
    home = _home(tmp_path)
    syncer = Raising(UpstreamUnavailable("uv is not installed, or 'uv' is not on PATH"))

    assert _main(home, "new", str(TRIAGE), syncer=syncer) == 6

    assert "uv is not installed" in capsys.readouterr().err

def test_an_installer_that_found_no_workspace_exits_three_like_any_other_absence(
    tmp_path: Path,
) -> None:
    """`NotFoundError` -> 3, through the same table every other command's absences resolve through.

    The scaffold makes the workspace before the installer is started, so this is not a state `agl
    new` can reach on its own - what it pins is that the adapter's refusal is not swallowed on the
    way past, and that a command growing its own answer for a missing workspace would have to
    disagree with `ports/errors.py`'s one table to do it.
    """
    home = _home(tmp_path)
    syncer = Raising(NotFoundError("there is no workspace to sync"))

    assert _main(home, "new", str(TRIAGE), syncer=syncer) == 3

# --- the refusals, through argv -----------------------------------------------------------------

@pytest.mark.parametrize(
    ("spelled", "rule"),
    [
        ("my-flow", "not a Python identifier"),
        ("triage.v2", "not a Python identifier"),
        ("2fast", "not a Python identifier"),
        ("class", "Python keyword"),
        ("a/b", "one path segment"),
        ("con", "device name"),
        ("", "it is empty"),
    ],
)
def test_a_name_that_cannot_be_all_three_things_at_once_is_refused_before_anything_is_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], spelled: str, rule: str
) -> None:
    """Exit 2, the broken rule named, and an AGL_HOME still absent afterwards.

    A workflow's name is its directory, the module imported from it and the key its declaration
    writes, and the three do not admit the same language: `my-flow` is a perfectly good directory
    and can never be a module. The refusal says which of them it failed, because "invalid name"
    leaves an operator guessing at a rule nothing on screen states - and it comes before the
    workspace is made, or a refused command leaves a home behind it.
    """
    home = _home(tmp_path)

    assert _main(home, "new", spelled) == 2

    assert rule in capsys.readouterr().err
    assert not home.path.exists(), "a refused `agl new` created something anyway"

def test_a_second_new_under_a_name_the_workspace_already_holds_exits_four(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`agl new` writes a workflow once and never over one - exit 4, and the first one intact.

    That is what the refusal is *for*: somebody who has written a workflow and types `agl new` with
    the same name again must not lose it. The module is edited first, so the assertion is about the
    operator's own text rather than about a file existing.
    """
    home = _home(tmp_path)
    _main(home, "new", str(TRIAGE))
    written = workflow_module(home, TRIAGE)
    written.write_text("# the operator's own workflow\n", encoding="utf-8")
    capsys.readouterr()

    assert _main(home, "new", str(TRIAGE)) == 4

    assert "already in your workspace" in capsys.readouterr().err
    assert written.read_text(encoding="utf-8") == "# the operator's own workflow\n"

def test_an_argument_too_many_on_a_new_line_is_refused_by_the_dispatch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`_dispatch`'s tail refusal, reached by the fifth command to share it, and nothing written."""
    home = _home(tmp_path)

    assert _main(home, "new", str(TRIAGE), "--from", "main") == 2

    assert "--from" in capsys.readouterr().err
    assert not home.path.exists(), "a refused `agl new` created something anyway"

# --- what the command is, read off the module ---------------------------------------------------

def test_the_new_parser_takes_one_positional_and_no_option_of_its_own() -> None:
    """One word to say, and it is the workflow's name. Everything else `agl new` works out itself.

    Where the workspace goes is AGL_HOME's answer and what a scaffold holds is this command's, so a
    `--path` or a `--template` here would be a second place one of those is decided.
    """
    parser = _new_parser()

    options = {flag for action in parser._actions for flag in action.option_strings}
    positionals = [action.dest for action in parser._actions if not action.option_strings]

    assert options == {"-h", "--help"}
    assert positionals == ["workflow"]

def test_the_command_calls_exactly_one_api_function() -> None:
    """"Commands stay dumb" made mechanical - the same scan the other command suites make.

    A `toml_file.` or a `Path(` here would be the scaffold's own text coming back into the CLI,
    which is the one place this command has to grow to stop being a command.
    """
    called = {
        node.attr
        for node in ast.walk(ast.parse(inspect.getsource(new_command)))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "api"
    }

    assert called == {"new_workflow"}

def test_the_command_never_asks_for_a_registered_repository(tmp_path: Path) -> None:
    """`agl new` takes the home and an installer - it runs before there is a project at all.

    `registered()` resolves a project settings file, and a workflow is written into the workspace
    rather than into any repository, so a clause calling it would make the on-ramp refuse
    everywhere it exists for. The install that now follows the scaffold changes nothing about
    that: a sync addresses the workflows an operator wrote, and those live under no repository -
    `container.real_syncer` takes no project for exactly that reason. `_never` on the `Invocation`
    is `main`'s own seam used as the instrument, which is why every test in this file goes through
    `_main`.
    """
    home = _home(tmp_path)

    assert _main(home, "new", str(TRIAGE)) == 0
    assert workflow_dir(home, TRIAGE).is_dir()
    assert workspace_pyproject(home).is_file()
