"""`agl sync`: the dependencies an operator's workflows declare, installed beside them.

Installing is uv's half and reaches this suite as a scripted answer, because a test that ran uv
would need an index. What is AGL's own is the workspace the installer is pointed at: it is made
where it is absent, so an operator who has typed nothing else meets a sync rather than the
adapter's refusal, and it is never written over, the file being theirs once it exists.

**A third step follows the install and only a finished one.** `write_editor_pth` puts the running
AGL within reach of the venv uv just built, which is the one thing a workflow imports that nothing
installs there. It is the only step a refusal skips, and both halves of that are asserted below.

**Nothing here reaches the operator's own home and nothing here starts a process.** `AGL_HOME` is
resolved from a mapping handed to `sources.resolve_settings`, every path is under `tmp_path`, and
the syncer is substituted through `main.Invocation`'s own `syncer` field - the seam `cli/main.py`
declares for exactly this, whose default is `container.real_syncer`. `registered` raises: a sync
addresses the workflows an operator wrote and no repository at all, so composing one would be the
defect.
"""

import ast
import inspect
import sysconfig
from pathlib import Path
from typing import Final
import pytest
import agl
from agl.adapters.uv.fake import FakeSyncer
from agl.cli import main
from agl.cli.commands import sync as sync_command
from agl.config import sources
from agl.ports.errors import NotFoundError, UpstreamUnavailable
from agl.ports.home_layout import (
    AglHome,
    workflows_dir,
    workspace_dir,
    workspace_editor_pth,
    workspace_pyproject,
    workspace_site_packages,
)
from agl.ports.ids import ProjectName
from agl.ports.sync import Syncer, SyncOutcome
from agl.sdk.params import RefusingParser

# `agl init` is the one command that reads `cwd`, and no invocation below is one; the field is not
# optional (`cli/main.py` argues why), so it carries a real path nothing here opens.
ELSEWHERE: Final = Path("/nowhere")

AGREED: Final = SyncOutcome(synced=True, status=0, output="")

# The `lib/` subdirectory this interpreter installs into, which is the one `agl sync` addresses:
# `adapters/uv/syncer.py` builds the venv for `sys.executable` and nothing else.
SEGMENT: Final = Path(sysconfig.get_path("purelib")).parent.name

class Recording(Syncer):
    """A syncer answering as scripted and keeping what it was asked, which `FakeSyncer` does not."""

    def __init__(self, outcome: SyncOutcome = AGREED) -> None:
        self.asked: list[Path] = []
        self._outcome = outcome

    async def sync(self, workspace: Path) -> SyncOutcome:
        self.asked.append(workspace)
        return self._outcome

class Raising(Syncer):
    """A syncer that raises what an adapter raises, so `main`'s one table answers for the class."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    async def sync(self, workspace: Path) -> SyncOutcome:
        raise self._error

def _never() -> tuple[ProjectName, object]:
    """A `Registered` that fails the test if a command calls it: `agl sync` takes no repository."""
    raise AssertionError("`agl sync` composed a repository")

def _home(tmp_path: Path) -> AglHome:
    """An AGL_HOME under `tmp_path`, which is not there yet unless a test puts something in it."""
    return AglHome(tmp_path / "home")

def _main(home: AglHome, syncer: Syncer, *argv: str) -> int:
    """One `agl` invocation reading `home`, with that syncer behind it and no repository at all."""
    return main.main(
        argv,
        compose=lambda: main.Invocation(
            registered=_never,  # type: ignore[arg-type]
            settings=sources.resolve_settings(sources.Overrides(), {"AGL_HOME": str(home.path)}),
            cwd=ELSEWHERE,
            points=None,
            syncer=lambda: syncer,
        ),
    )

def _installed(home: AglHome) -> Path:
    """The venv uv would have built, stood up by hand: `FakeSyncer` starts no process at all."""
    workspace_site_packages(home, SEGMENT).mkdir(parents=True)
    return workspace_editor_pth(home, SEGMENT)

def _sync_parser() -> RefusingParser:
    """The `sync` subparser alone, built the way `main.parser()` builds it, for inspection."""
    root = RefusingParser(prog="agl", allow_abbrev=False)
    commands = root.add_subparsers(dest="command", required=True, parser_class=RefusingParser)
    return sync_command.declare(commands)

# --- what the installer is pointed at ---------------------------------------------------------

def test_the_installer_is_handed_the_workspace_directory_and_not_its_project_file(
    tmp_path: Path,
) -> None:
    """`Syncer.sync` takes the directory, and uv walks *up* from whatever it is given.

    Handing it the `pyproject.toml` would be a path uv reads as a directory that is not there;
    handing it `workflows/` would resolve the first project file above it, which is the workspace
    root by luck rather than by intent. `adapters/uv/syncer.py` refuses a directory with no
    project file in it for the same family of reasons, and this is the caller's half of that.
    """
    home = _home(tmp_path)
    syncer = Recording()

    assert _main(home, syncer, "sync") == 0

    assert syncer.asked == [workspace_dir(home)]

# --- what it makes on the way ---------------------------------------------------------------------

def test_a_sync_where_no_workspace_exists_makes_one_rather_than_reporting_it_missing(
    tmp_path: Path,
) -> None:
    """An operator who has typed nothing else meets a sync, not a `NotFoundError`.

    `UvSyncer.sync` raises where the directory it is given holds no project file, and it is right
    to - uv would otherwise install some ancestor project's dependencies. But that refusal belongs
    to the adapter's contract and not to this command's grammar, so `agl sync` makes the workspace
    first, exactly as `agl new` does, and for the same reason: the workspace is AGL's to make.
    """
    home = _home(tmp_path)
    assert not home.path.exists()

    assert _main(home, FakeSyncer(), "sync") == 0

    assert workspace_pyproject(home).is_file()
    assert workflows_dir(home).is_dir()

def test_a_sync_over_a_workspace_that_already_exists_leaves_its_file_byte_for_byte(
    tmp_path: Path,
) -> None:
    """A workspace that is already there is not rewritten, and the bytes are the assertion.

    The paths would look identical either way, which is why this is over the contents: the operator
    owns that file once it exists, and a command that rewrote it on every invocation would be one
    interrupted write away from taking their own lines with it, every time it was run.
    """
    home = _home(tmp_path)
    assert _main(home, FakeSyncer(), "sync") == 0
    edited = workspace_pyproject(home)
    edited.write_text(
        edited.read_text(encoding="utf-8") + "\n# an operator's own line\n", encoding="utf-8"
    )
    before = edited.read_bytes()

    assert _main(home, FakeSyncer(), "sync") == 0

    assert edited.read_bytes() == before

def test_a_finished_sync_leaves_the_workspace_venv_naming_the_agl_that_ran_it(
    tmp_path: Path,
) -> None:
    """The third step, and the reason it is here: nothing installs AGL into that venv.

    `agl new` writes a workflow whose first line imports `agl.sdk`, and neither the workspace root
    nor the scaffold declares AGL as a dependency - `tests/config/test_toml_file.py` holds that,
    and it is deliberate, AGL being on the import path rather than installed into it. So an editor
    with the workspace venv selected has every package the workflow declares and not the one it
    imports first, and this file is what closes that gap. It closes it for an editor alone:
    `config/workspace_path.py` says why no run of AGL reads it.
    """
    home = _home(tmp_path)
    pth = _installed(home)

    assert _main(home, FakeSyncer(), "sync") == 0

    assert agl.__file__ is not None
    assert pth.read_text(encoding="utf-8") == f"{Path(agl.__file__).parent.parent}\n"

def test_a_refused_sync_writes_no_path_file_into_the_venv_it_did_not_build(
    tmp_path: Path,
) -> None:
    """The one step a refusal skips, and it is skipped because of what the file would claim.

    uv exiting non-zero is every failure at once - a resolution with no solution, an index that
    could not be reached, a package that would not build - and what it leaves behind is a venv
    that may hold nothing, or may not be there at all. A file written into it would name this AGL
    beside an environment that was never finished, and `agl sync` exits 6 saying the install did
    not happen. So the two agree: nothing installed, nothing claimed.
    """
    home = _home(tmp_path)
    pth = _installed(home)
    syncer = Recording(SyncOutcome(synced=False, status=2, output="error: no solution found\n"))

    assert _main(home, syncer, "sync") == 6

    assert not pth.exists()

# --- what it says, and what a script reads -------------------------------------------------------

def test_a_finished_sync_prints_what_the_installer_said_and_says_it_finished(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """uv's own output, whole, and then one line of AGL's - both on stdout, and exit 0.

    The installer's text is passed through rather than summarised because AGL knows nothing about
    what it says: which packages resolved, what was already cached and what it built are uv's
    facts, and a command that swallowed them would leave an operator watching a silent minute.
    """
    home = _home(tmp_path)
    syncer = Recording(SyncOutcome(synced=True, status=0, output="Installed 3 packages\n"))

    assert _main(home, syncer, "sync") == 0

    captured = capsys.readouterr()
    assert captured.out == "Installed 3 packages\nsync finished\n"
    assert captured.err == ""

def test_a_refused_sync_exits_six_and_carries_the_whole_output_with_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A non-zero exit from uv is an upstream failure - exit 6 - and never a success with a warning.

    The status uv gave is named as well as the text, because the two answer different questions: a
    script branches on AGL's 6 and a person reads uv's own words for what could not be resolved.
    The output leaves with the refusal rather than on stdout, so this command writes nothing to
    stdout at all on the path where nothing was installed.
    """
    home = _home(tmp_path)
    syncer = Recording(SyncOutcome(synced=False, status=2, output="error: no solution found\n"))

    assert _main(home, syncer, "sync") == 6

    captured = capsys.readouterr()
    assert "error: no solution found" in captured.err
    assert "uv exited 2" in captured.err
    assert captured.out == ""

def test_an_installer_that_could_not_be_started_exits_six_saying_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`UpstreamUnavailable` -> 6, and the adapter's sentence arrives unreworded.

    That is the shape of "uv is not installed", which is the commonest way this command fails on a
    machine that has never run it: `adapters/uv/syncer.py` writes the sentence where the facts are
    - the binary it looked for, and three ways to install one - and nothing on the way up edits it.
    """
    home = _home(tmp_path)
    syncer = Raising(UpstreamUnavailable("uv is not installed, or 'uv' is not on PATH"))

    assert _main(home, syncer, "sync") == 6

    assert "uv is not installed" in capsys.readouterr().err

def test_an_installer_that_found_no_workspace_exits_three_like_any_other_absence(
    tmp_path: Path,
) -> None:
    """`NotFoundError` -> 3, through the same table every other command's absences resolve through.

    The command makes the workspace before it syncs, so this is not a state `agl sync` can reach
    on its own - what it pins is that the adapter's refusal is not swallowed on the way past, and
    that a command growing its own answer for a missing workspace would have to disagree with
    `ports/errors.py`'s one table to do it.
    """
    home = _home(tmp_path)
    syncer = Raising(NotFoundError("there is no workspace to sync"))

    assert _main(home, syncer, "sync") == 3

# --- what the command is, read off the module ----------------------------------------------------

def test_the_sync_parser_takes_no_argument_of_its_own_at_all() -> None:
    """Nothing to say: the workspace is AGL_HOME's answer and the installer is the container's.

    A `--workspace` here would be a second place the first is decided, and a `--python` a second
    place the second is - `adapters/uv/syncer.py` passes this process's own interpreter, because
    `config/workspace_path.py` composes the site-packages directory from it.
    """
    parser = _sync_parser()

    options = {flag for action in parser._actions for flag in action.option_strings}
    positionals = [action.dest for action in parser._actions if not action.option_strings]

    assert options == {"-h", "--help"}
    assert positionals == []

def test_an_argument_too_many_on_a_sync_line_is_refused_by_the_dispatch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`_dispatch`'s tail refusal, reached by the sixth command to share it, and nothing synced."""
    home = _home(tmp_path)
    syncer = Recording()

    assert _main(home, syncer, "sync", "--from", "main") == 2

    assert "--from" in capsys.readouterr().err
    assert syncer.asked == []

def test_the_command_calls_exactly_one_api_function() -> None:
    """"Commands stay dumb" made mechanical - the same scan the other command suites make.

    A `toml_file.` or a `workspace_dir(` here would be the ordering of the three steps coming back
    into the CLI, which is where a later command that also syncs would then have to copy it from.
    """
    called = {
        node.attr
        for node in ast.walk(ast.parse(inspect.getsource(sync_command)))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "api"
    }

    assert called == {"sync_workspace"}

def test_the_command_never_asks_for_a_registered_repository(tmp_path: Path) -> None:
    """A sync addresses the workflows an operator wrote, and those live under no repository.

    `_never` on the `Invocation` is `main`'s own seam used as the instrument, which is why every
    test in this file goes through `_main` - and it is the same claim `agl new` and `agl workflows`
    make, the three of them being the commands that answer before there is a project at all.
    """
    home = _home(tmp_path)

    assert _main(home, FakeSyncer(), "sync") == 0
    assert workspace_pyproject(home).is_file()

def test_the_real_syncer_is_the_default_behind_the_seam_this_suite_substitutes(
    tmp_path: Path,
) -> None:
    """The seam is a field with a real default, spelled the way `compose=` and `points=` are.

    Every test above hands in a syncer, so without this the suite would be compatible with an
    `Invocation` whose default was a fake - and `agl sync` typed at a terminal would install
    nothing while reporting that it had. Constructing a `UvSyncer` resolves no binary and starts
    nothing, which is what makes the default safe to build here.
    """
    invocation = main.Invocation(
        registered=_never,  # type: ignore[arg-type]
        settings=sources.resolve_settings(
            sources.Overrides(), {"AGL_HOME": str(_home(tmp_path).path)}
        ),
        cwd=ELSEWHERE,
    )

    assert isinstance(invocation.syncer(), Syncer)
    assert not isinstance(invocation.syncer(), FakeSyncer)
