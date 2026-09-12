"""`agl update [<workflow>]`: the command, its summary, its streams and its exit status.

`api.update` decides - `config/comparison.py` finds what `agl get` placed, asks which commit each
one's ref names now and measures each copy that moved, and `get`'s own phases download, inspect, ask
and place - and this file drives it through `main`, the way an operator reaches it, on a
`FakeFetcher` that counts every question asked of it and every download. The real fetcher runs
twice, against `instruments.github_api`'s and `instruments.codeload`'s stand-ins on 127.0.0.1.

**The common case is one line.** Every downloaded workflow current says `already up to date` on
stderr and nothing else anywhere - no prompt, no line per workflow, exit 0 - however many there
are. A workspace where `agl get` placed nothing is current too: nothing it could check has moved,
and a workflow written by hand or by `agl new` is not this command's business, so it is not
mentioned. Where something did move, the current ones stay unmentioned beside it.

**The summary is `agl get`'s.** A word in the first column - `updated`, `declined` or `refused` -
then the entry's name and the workflow as `agl get` spells one; an `updated` line ends in the
commit it was placed from and the one it is at now, and every other line in a few words saying why.
Each refusal's whole reason follows once, naming every workflow it refused.

**The streams.** An `updated` line goes to stdout, because it names a workflow the workspace now
holds; everything else is a note, and goes to stderr with the questions.

**The exit status.** A decline is the operator's answer, so a command whose every moved workflow
was updated or declined exits 0 - under `< /dev/null` too. Refusals resolve by
`cli/commands/__init__.py`'s `_refusal_status`, whichever phase made them: the code they share, or
8 where they differ. A copy changed after it was measured is refused as it is about to be replaced,
`(not written)` and 4. A name `agl get` never placed, or nothing holds, exits 3 before any question
is asked. A sync that fails after the placing is one more reason, written once below the summary,
and its 6 joins the refusals as it does under `agl get`: 6 alone, 8 beside a 3.

**Every door out is substituted through `main.Invocation`**: the fetcher, the syncer and, where a
test answers for the operator, `confirm`. Where it does not, `sys.stdin` is replaced and the real
`confirm` reads it, as `tests/cli/test_get_command.py` does. The repository behind every invocation
here raises if anything so much as builds one.
"""

import ast
import contextlib
import dataclasses
import inspect
import io
import os
import sys
import sysconfig
from collections.abc import Callable
from pathlib import Path
from typing import Final
import pytest
from agl.adapters.github.fake import FakeFetcher
from agl.adapters.github.fetcher import GitHubFetcher
from agl.adapters.uv.fake import FakeSyncer
from agl.cli import main
from agl.cli.commands import update as update_command
from agl.config import registry, sources
from agl.config.provenance import Provenance, placed_hash, read_provenance, rendered
from agl.config.questions import Confirm
from agl.ports.errors import NotFoundError, UpstreamUnavailable
from agl.ports.fetch import FetchedFile, Fetcher
from agl.ports.get_request import RepositoryAtRef, RequestedWorkflow
from agl.ports.home_layout import (
    PROVENANCE_FILE,
    AglHome,
    workflows_dir,
    workspace_dir,
    workspace_site_packages,
)
from agl.ports.ids import ProjectName
from agl.ports.sync import Syncer, SyncOutcome
from agl.sdk._engine.services import Services
from agl.sdk.params import RefusingParser
from instruments.codeload import Codeload, archive, tree
from instruments.github_api import GitHubApi

# Never opened: `agl update` reads the home it is handed and no working directory.
ELSEWHERE: Final = Path("/nowhere")

_PLACED_FROM: Final = "0b496e91ec7ae4428c3ed2eeb4c3a40df431f2cc"
_NOW: Final = "f548e57e544e1ff5a4c46bf1e1b8685f8e4a348a"
_LATER: Final = "a5b1c2d3e4f5061728394a5b6c7d8e9f00112233"

_FLOWS: Final = RepositoryAtRef("octo", "flows", None)
_RELEASED: Final = RepositoryAtRef("octo", "flows", "release/1.0")
_TOOLS: Final = RepositoryAtRef("octo", "tools", "v2")
_CHECKS: Final = RepositoryAtRef("jashioq", "checks", None)
_NOWHERE: Final = RepositoryAtRef("octo", "nope", None)

_CURRENT: Final = "already up to date\n"

_MODULE: Final = b"from agl.sdk import Run, workflow\n"
_MODULE_NOW: Final = b"from agl.sdk import Run, workflow\n\n# as upstream has it now\n"

_UV_SAID: Final = "error: no solution found for moved\n"

_UV_MISSING: Final = "uv is not installed, or 'uv' is not on PATH"

# How each installer failure below reads on stderr: the first two in the line `main` prints for any
# refusal, the third as the warning `api._unchanged` writes.
_SAID_MISSING: Final = f"agl: {_UV_MISSING}"
_SAID_REFUSED: Final = "agl: the sync was refused: uv exited 2 rather than 0"
_WARNED: Final = "warning: the sync was refused - uv exited 2 rather than 0"

# The reasons `_gone`, `_hollow` and `_unanswered` refuse with: 3, 2 and 6.
_GONE: Final = "gone: the fake fetcher serves no repository octo/nope"
_HOLLOW: Final = "hollow: octo/flows/workflows/hollow holds no pyproject.toml"
_UNANSWERED: Final = "check: api.github.com did not answer for jashioq/checks"

# The `lib/` subdirectory this interpreter installs into, which is the one a sync addresses.
SEGMENT: Final = Path(sysconfig.get_path("purelib")).parent.name

class _NoSync(Syncer):
    """A syncer that fails the test if anything is installed, for runs that placed nothing."""

    async def sync(self, workspace: Path) -> SyncOutcome:
        raise AssertionError(f"`agl update` installed into {workspace} with nothing placed")

class _Raising(Syncer):
    """A syncer that raises what an adapter raises, so `main`'s one table answers for the class."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    async def sync(self, workspace: Path) -> SyncOutcome:
        raise self._error

def _never() -> tuple[ProjectName, Services]:
    raise AssertionError("`agl update` composed a repository")

def _asking_nothing(question: str) -> bool:
    raise AssertionError(f"`agl update` asked {question!r}, where there was nothing to ask")

def _no(question: str) -> bool:
    return False

def _home(tmp_path: Path) -> AglHome:
    return AglHome(tmp_path / "home")

def _pyproject(name: str, dependencies: str = "") -> bytes:
    return (
        f'[project]\nname = "{name}"\nversion = "0.1.0"\n{dependencies}\n'
        f'[project.entry-points."{registry.GROUP}"]\n{name} = "{name}:{name}"\n'
    ).encode()

def _workflow(home: AglHome, directory: str, *, name: str | None = None) -> Path:
    """A workflow directory as `agl new` or a person writes one: a project file and a module."""
    entry = workflows_dir(home) / directory
    entry.mkdir(parents=True)
    (entry / "pyproject.toml").write_bytes(_pyproject(name or directory))
    (entry / "__init__.py").write_bytes(_MODULE)
    return entry

def _placed(
    home: AglHome,
    directory: str,
    repository: RepositoryAtRef,
    *,
    commit: str = _PLACED_FROM,
    placed_as: str | None = None,
) -> Path:
    """A workflow directory as `agl get` leaves one: its files, and the provenance it wrote last.

    `placed_as` is the name `agl get` placed it under, where the entry has been renamed since.
    """
    entry = _workflow(home, directory, name=placed_as)
    unspelled = RequestedWorkflow(repository, f"workflows/{placed_as or directory}", "")
    provenance = Provenance(
        dataclasses.replace(unspelled, spec=str(unspelled)), commit, placed_hash(entry)
    )
    (entry / PROVENANCE_FILE).write_bytes(rendered(provenance))
    return entry

def _serving(
    fetcher: FakeFetcher,
    repository: RepositoryAtRef,
    *names: str,
    commit: str = _NOW,
    depending: dict[str, str] | None = None,
    hollow: tuple[str, ...] = (),
) -> FakeFetcher:
    """`repository` at `commit`: each named workflow as upstream has it now, and hollow ones.

    A name in `hollow` holds no project file, so it is refused on inspection.
    """
    files: dict[str, FetchedFile] = {}
    for name in names:
        written = _pyproject(name, (depending or {}).get(name, ""))
        files[f"workflows/{name}/pyproject.toml"] = FetchedFile(written)
        files[f"workflows/{name}/__init__.py"] = FetchedFile(_MODULE_NOW)
    for name in hollow:
        files[f"workflows/{name}/__init__.py"] = FetchedFile(_MODULE_NOW)
    fetcher.serves(repository, files, commit=commit)
    return fetcher

def _changed(entry: Path) -> None:
    """The operator's own edit to a placed copy: a line added to its module."""
    with (entry / "__init__.py").open("ab") as module:
        module.write(b"# mine\n")

def _main(
    home: AglHome,
    *argv: str,
    fetcher: Fetcher,
    syncer: Syncer | None = None,
    confirm: Confirm | None = _asking_nothing,
) -> int:
    """One `agl` invocation reading `home`, with no repository behind it.

    `confirm` handed as `None` is the real one, reading whatever the test put on `sys.stdin`.
    """
    installer = FakeSyncer() if syncer is None else syncer

    def compose() -> main.Invocation:
        invocation = main.Invocation(
            registered=_never,
            settings=sources.resolve_settings(sources.Overrides(), {"AGL_HOME": str(home.path)}),
            cwd=ELSEWHERE,
            syncer=lambda: installer,
            fetcher=lambda: fetcher,
        )
        return invocation if confirm is None else dataclasses.replace(invocation, confirm=confirm)

    return main.main(argv, compose=compose)

def _written(
    home: AglHome,
    *argv: str,
    fetcher: Fetcher,
    syncer: Syncer,
    confirm: Confirm = _asking_nothing,
) -> tuple[int, str]:
    """The exit status, and both streams as one, in the order the command wrote to them.

    `capsys` keeps stdout and stderr apart, and what a caller of this asserts is which came first.
    """
    both = io.StringIO()
    with contextlib.redirect_stdout(both), contextlib.redirect_stderr(both):
        status = _main(home, *argv, fetcher=fetcher, syncer=syncer, confirm=confirm)
    return status, both.getvalue()

def _uv_missing(home: AglHome) -> Syncer:
    """The first rule: an installer that could not be started, raising what `UvSyncer` raises."""
    return _Raising(UpstreamUnavailable(_UV_MISSING))

def _uv_refusing(home: AglHome) -> Syncer:
    """uv exiting 2 on `home`'s workspace: the second rule, or the third where a venv stands."""
    installer = FakeSyncer()
    installer.answers(workspace_dir(home), synced=False, status=2, output=_UV_SAID)
    return installer

def _moved(home: AglHome) -> FakeFetcher:
    """`moved`, placed from `octo/tools@v2` and moved on since: updated, and synced for."""
    _placed(home, "moved", _TOOLS)
    return _serving(FakeFetcher(), _TOOLS, "moved")

def _gone(home: AglHome, fetcher: FakeFetcher) -> None:
    """A workflow placed from a repository the fetcher does not have: refused unchecked, 3."""
    _placed(home, "gone", _NOWHERE)

def _hollow(home: AglHome, fetcher: FakeFetcher) -> None:
    """A workflow whose ref moved to a download holding no project file: refused unplaceable, 2."""
    _placed(home, "hollow", _FLOWS)
    _serving(fetcher, _FLOWS, hollow=("hollow",))

def _unanswered(home: AglHome, fetcher: FakeFetcher) -> None:
    """A workflow placed from a repository that did not answer: refused unchecked, 6."""
    _placed(home, "check", _CHECKS)
    fetcher.refuses(
        _CHECKS, UpstreamUnavailable("api.github.com did not answer for jashioq/checks")
    )

def _words(stream: str) -> list[list[str]]:
    """Each line split on whitespace, which is how a script reads a column."""
    return [line.split() for line in stream.splitlines()]

def _update_parser() -> RefusingParser:
    """The `update` subparser alone, built the way `main.parser()` builds it, for inspection."""
    root = RefusingParser(prog="agl", allow_abbrev=False)
    commands = root.add_subparsers(dest="command", required=True, parser_class=RefusingParser)
    return update_command.declare(commands)

# --- nothing moved ------------------------------------------------------------------------------

def test_ten_workflows_all_current_say_already_up_to_date_and_nothing_else_anywhere(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The brief's own case, exactly: one line, exit 0, no question - and four refs asked, not ten.

    Ten workflows from three repositories at four refs, a hand-written workflow beside them that is
    never mentioned, and a fetcher that would answer a download if one were asked for and is not.
    Nothing is installed either: nothing was placed.
    """
    home = _home(tmp_path)
    for index in range(4):
        _placed(home, f"flow_{index}", _FLOWS)
    for index in range(3):
        _placed(home, f"release_{index}", _RELEASED)
    for index in range(2):
        _placed(home, f"tool_{index}", _TOOLS)
    _placed(home, "check", _CHECKS)
    _workflow(home, "hand_written")
    fetcher = FakeFetcher()
    for repository in (_FLOWS, _RELEASED, _TOOLS, _CHECKS):
        fetcher.serves(repository, {}, commit=_PLACED_FROM)

    status = _main(home, "update", fetcher=fetcher, syncer=_NoSync())

    captured = capsys.readouterr()
    assert (status, captured.out, captured.err) == (0, "", _CURRENT)
    assert fetcher.resolved == (_CHECKS, _FLOWS, _RELEASED, _TOOLS)
    assert fetcher.fetched == ()

def test_a_workspace_where_agl_get_placed_nothing_is_already_up_to_date_too(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Hand-written and scaffolded workflows are not this command's business, and not a nag."""
    home = _home(tmp_path)
    _workflow(home, "hand_written")
    _workflow(home, "scaffolded")
    fetcher = FakeFetcher()

    status = _main(home, "update", fetcher=fetcher, syncer=_NoSync())

    captured = capsys.readouterr()
    assert (status, captured.out, captured.err) == (0, "", _CURRENT)
    assert fetcher.resolved == ()

def test_a_home_that_is_not_there_yet_is_already_up_to_date_and_is_never_made(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = _home(tmp_path)

    status = _main(home, "update", fetcher=FakeFetcher(), syncer=_NoSync())

    assert (status, capsys.readouterr().err) == (0, _CURRENT)
    assert not home.path.exists()

def test_one_named_workflow_that_is_current_says_already_up_to_date_and_asks_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = _home(tmp_path)
    _placed(home, "triage", _FLOWS)
    _placed(home, "tool", _TOOLS)
    fetcher = FakeFetcher()
    fetcher.serves(_TOOLS, {}, commit=_PLACED_FROM)

    status = _main(home, "update", "tool", fetcher=fetcher)

    captured = capsys.readouterr()
    assert (status, captured.out, captured.err) == (0, "", _CURRENT)
    assert fetcher.resolved == (_TOOLS,)

# --- something moved ----------------------------------------------------------------------------

def test_a_workflow_whose_ref_moved_is_updated_and_named_on_stdout_with_both_short_commits(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One download, one line; the current workflow beside it is neither mentioned nor fetched."""
    home = _home(tmp_path)
    triage = _placed(home, "triage", _FLOWS)
    _placed(home, "tool", _TOOLS)
    fetcher = _serving(FakeFetcher(), _FLOWS, "triage")
    fetcher.serves(_TOOLS, {}, commit=_PLACED_FROM)

    status = _main(home, "update", fetcher=fetcher)

    captured = capsys.readouterr()
    assert (status, captured.out, captured.err) == (
        0,
        "updated   triage  octo/flows/workflows/triage  0b496e9 -> f548e57\n",
        "",
    )
    assert [fetch.repository for fetch in fetcher.fetched] == [_FLOWS]
    assert (triage / "__init__.py").read_bytes() == _MODULE_NOW

def test_an_updated_line_names_the_commit_its_own_copy_was_placed_from_not_a_renamed_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A renamed copy recording an older commit of the same workflow stands beside it, refused.

    The copy has been made the operator's own, declaring its own name, so nothing clashes and the
    workflow it was copied from is updated - from the commit that one recorded.
    """
    home = _home(tmp_path)
    _placed(home, "triage", _FLOWS)
    copy = _placed(home, "triage_old", _FLOWS, commit=_LATER, placed_as="triage")
    (copy / "pyproject.toml").write_bytes(_pyproject("triage_old"))

    status = _main(home, "update", fetcher=_serving(FakeFetcher(), _FLOWS, "triage"))

    captured = capsys.readouterr()
    assert status == 4
    assert captured.out == "updated   triage      octo/flows/workflows/triage  0b496e9 -> f548e57\n"
    assert _words(captured.err)[0] == [
        "refused", "triage_old", "octo/flows/workflows/triage", "(not", "replaceable)"
    ]

def test_an_updated_workflow_is_the_one_kind_of_line_that_goes_to_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Updated on stdout; declined, refused, the reasons and the questions all on stderr.

    One of each: `triage` moved and is updated, `lint` moved and changed since it was placed and
    the operator keeps it, `release_old` stands under another name than it was placed as, and
    `gone` names a repository that is not there.
    """
    home = _home(tmp_path)
    _placed(home, "triage", _FLOWS)
    _changed(_placed(home, "lint", _FLOWS))
    _placed(home, "release_old", _FLOWS, placed_as="release")
    _placed(home, "gone", _NOWHERE)
    fetcher = _serving(FakeFetcher(), _FLOWS, "triage", "lint", "release")

    status = _main(home, "update", fetcher=fetcher, confirm=_no)

    captured = capsys.readouterr()
    assert status == 8
    assert _words(captured.out) == [
        ["updated", "triage", "octo/flows/workflows/triage", "0b496e9", "->", "f548e57"]
    ]
    assert _words(captured.err)[:3] == [
        ["declined", "lint", "octo/flows/workflows/lint", "(local", "changes", "kept)"],
        ["refused", "gone", "octo/nope/workflows/gone", "(not", "checked)"],
        ["refused", "release_old", "octo/flows/workflows/release", "(not", "replaceable)"],
    ]

def test_the_summary_lines_its_columns_up_and_says_why_each_skipped_workflow_was_skipped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The layout as `agl get` lays one out: the marker column, the name column, the workflow.

    The marker is as wide as the widest word and the name as wide as the widest name in the whole
    summary, both streams counted, so the two streams line up where a terminal shows them as one.
    """
    home = _home(tmp_path)
    _placed(home, "triage", _FLOWS)
    _changed(_placed(home, "lint", _FLOWS))
    moved_away = _placed(home, "release_old", _FLOWS, placed_as="release")
    fetcher = _serving(FakeFetcher(), _FLOWS, "triage", "lint", "release")

    _main(home, "update", fetcher=fetcher, confirm=_no)

    captured = capsys.readouterr()
    assert captured.out == (
        "updated   triage       octo/flows/workflows/triage  0b496e9 -> f548e57\n"
    )
    written = captured.err.splitlines()
    assert written[:2] == [
        "declined  lint         octo/flows/workflows/lint  (local changes kept)",
        "refused   release_old  octo/flows/workflows/release  (not replaceable)",
    ]
    assert written[2].startswith(f"release_old: {moved_away} holds the provenance of ")
    assert len(written) == 3

def test_a_workflow_gaining_a_dependency_is_asked_and_declined_says_so_and_never_prints_it_raw(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`packaging` lets an escape through in a requirement's URL, and a terminal would act on one.

    The question shows each dependency it names as a literal and the summary names the question
    rather than the packages, so no byte of the declaration reaches either stream as itself.
    """
    home = _home(tmp_path)
    kept = _placed(home, "lint", _FLOWS)
    before = (kept / "pyproject.toml").read_bytes()
    monkeypatch.setattr(sys, "stdin", io.StringIO("n\n"))
    escaped = 'dependencies = ["evil @ https://example.com/\\u001b[2J.whl"]'
    fetcher = _serving(FakeFetcher(), _FLOWS, "lint", depending={"lint": escaped})

    assert _main(home, "update", fetcher=fetcher, confirm=None) == 0

    captured = capsys.readouterr()
    assert "declares third-party dependencies" in captured.err
    assert "(new third-party dependencies)" in captured.err
    assert "\x1b" not in captured.err
    assert "\x1b" not in captured.out
    assert (kept / "pyproject.toml").read_bytes() == before

# --- the exit status ----------------------------------------------------------------------------

def test_with_stdin_at_its_end_a_changed_copy_is_kept_and_the_command_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`< /dev/null`: the real `confirm` meets end of file and takes it as no, for every question.

    The operator's changes are the thing an update could destroy, so the answer nobody gave keeps
    them - byte for byte - and nothing is refused, so the status is 0 and stdout is empty.
    """
    home = _home(tmp_path)
    entry = _placed(home, "triage", _FLOWS)
    _changed(entry)
    kept = {path.name: path.read_bytes() for path in entry.iterdir()}
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    status = _main(
        home, "update", fetcher=_serving(FakeFetcher(), _FLOWS, "triage"), confirm=None
    )

    captured = capsys.readouterr()
    assert status == 0
    assert captured.out == ""
    assert "has changed since it was placed from 0b496e9" in captured.err
    assert captured.err.count("stdin was closed, and that is taken as no") == 1
    assert {path.name: path.read_bytes() for path in entry.iterdir()} == kept

def test_one_refusal_exits_with_its_own_code_and_says_why_once_naming_each_workflow(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Two workflows from a repository that is not there: one reason, both names, exit 3."""
    home = _home(tmp_path)
    _placed(home, "alpha", _NOWHERE)
    _placed(home, "beta", _NOWHERE)

    status = _main(home, "update", fetcher=FakeFetcher())

    captured = capsys.readouterr()
    assert status == 3
    assert captured.out == ""
    assert captured.err == (
        "refused   alpha  octo/nope/workflows/alpha  (not checked)\n"
        "refused   beta   octo/nope/workflows/beta  (not checked)\n"
        "alpha, beta: the fake fetcher serves no repository octo/nope\n"
    )

def test_refusals_that_disagree_exit_eight_through_main_and_every_other_workflow_is_updated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A provenance file that will not read is 2 and a repository that is not there is 3: 8.

    The moved workflow among them is still updated, because every failure refuses what it touched
    and nothing else. A provenance file that will not read names no workflow at all.
    """
    home = _home(tmp_path)
    broken = _placed(home, "broken", _FLOWS)
    (broken / PROVENANCE_FILE).write_bytes(b"{not json\n")
    _placed(home, "gone", _NOWHERE)
    _placed(home, "moved", _TOOLS)
    fetcher = _serving(FakeFetcher(), _TOOLS, "moved")
    fetcher.refuses(_NOWHERE, NotFoundError("api.github.com has no public repository octo/nope"))

    status = _main(home, "update", fetcher=fetcher)

    captured = capsys.readouterr()
    written = captured.err.splitlines()
    assert status == 8
    assert captured.out == "updated   moved   octo/tools/workflows/moved@v2  0b496e9 -> f548e57\n"
    assert written[:2] == [
        "refused   broken    (not checked)",
        "refused   gone    octo/nope/workflows/gone  (not checked)",
    ]
    assert written[2].startswith(f"broken: {broken / PROVENANCE_FILE} is not a provenance file")
    assert written[3] == "gone: api.github.com has no public repository octo/nope"

def test_refusals_made_in_every_phase_exit_eight_through_main_each_reason_said_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A ref not there (3), a renamed copy and a linked one (4 each), a download no workflow (2)."""
    home = _home(tmp_path)
    _placed(home, "gone", _NOWHERE)
    _placed(home, "triage_old", _FLOWS, placed_as="triage")
    elsewhere = _placed(AglHome(tmp_path / "elsewhere"), "linked", _FLOWS)
    (workflows_dir(home) / "linked").symlink_to(elsewhere, target_is_directory=True)
    _placed(home, "hollow", _FLOWS)
    fetcher = _serving(FakeFetcher(), _FLOWS, hollow=("hollow",))

    status = _main(home, "update", fetcher=fetcher)

    written = capsys.readouterr().err.splitlines()
    assert status == 8
    assert [line.split()[:2] for line in written[:4]] == [
        ["refused", "gone"],
        ["refused", "linked"],
        ["refused", "triage_old"],
        ["refused", "hollow"],
    ]
    assert [line.split(":")[0] for line in written[4:]] == [
        "gone",
        "linked",
        "triage_old",
        "hollow",
    ]

def test_a_copy_edited_while_its_question_is_up_is_not_written_and_exits_four(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The yes covered the edit the copy held when it was measured, and not one saved after it.

    The workflow beside it is updated and named on stdout, and the refusal is filed where `agl get`
    files one made as it writes: `(not written)`, its reason once on stderr, the copy as left.
    """
    home = _home(tmp_path)
    triage = _placed(home, "triage", _FLOWS)
    _changed(triage)
    _placed(home, "lint", _FLOWS)
    kept: dict[str, bytes] = {}

    def editing_again(question: str) -> bool:
        with (triage / "__init__.py").open("ab") as module:
            module.write(b"# saved while the question was up\n")
        kept.update({path.name: path.read_bytes() for path in triage.iterdir()})
        return True

    fetcher = _serving(FakeFetcher(), _FLOWS, "triage", "lint")
    status = _main(home, "update", fetcher=fetcher, confirm=editing_again)

    captured = capsys.readouterr()
    written = captured.err.splitlines()
    assert status == 4
    assert captured.out == "updated   lint    octo/flows/workflows/lint  0b496e9 -> f548e57\n"
    assert written[0] == "refused   triage  octo/flows/workflows/triage  (not written)"
    assert written[1].startswith(f"triage: {triage} changed after `agl update` measured it")
    assert len(written) == 2
    assert {path.name: path.read_bytes() for path in triage.iterdir()} == kept

def test_a_copy_edited_meanwhile_beside_a_refusal_with_another_code_exits_eight(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A repository that is not there refuses with 3, and the copy edited meanwhile with 4."""
    home = _home(tmp_path)
    triage = _placed(home, "triage", _FLOWS)
    _changed(triage)
    _placed(home, "gone", _NOWHERE)

    def editing_again(question: str) -> bool:
        _changed(triage)
        return True

    fetcher = _serving(FakeFetcher(), _FLOWS, "triage")
    status = _main(home, "update", fetcher=fetcher, confirm=editing_again)

    written = capsys.readouterr().err.splitlines()
    assert status == 8
    assert [line.split()[:2] for line in written[:2]] == [
        ["refused", "gone"],
        ["refused", "triage"],
    ]

# --- names, and the dispatch --------------------------------------------------------------------

def test_a_named_workflow_agl_get_never_placed_exits_three_before_anything_is_asked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = _home(tmp_path)
    hand_written = _workflow(home, "hand_written")
    fetcher = FakeFetcher()

    status = _main(home, "update", "hand_written", fetcher=fetcher)

    assert status == 3
    assert capsys.readouterr().err.startswith(f"agl: {hand_written} holds no {PROVENANCE_FILE}")
    assert fetcher.resolved == ()

def test_a_name_nothing_in_workflows_holds_exits_three_naming_what_agl_get_placed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = _home(tmp_path)
    _placed(home, "triage", _FLOWS)

    assert _main(home, "update", "lint", fetcher=FakeFetcher()) == 3

    assert "What `agl get` placed there: 'triage'." in capsys.readouterr().err

def test_an_argument_too_many_on_an_update_line_is_refused_by_the_dispatch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One workflow per command, or all of them: a second name is the dispatch's refusal."""
    home = _home(tmp_path)
    _placed(home, "triage", _FLOWS)
    fetcher = FakeFetcher()

    assert _main(home, "update", "triage", "lint", fetcher=fetcher) == 2

    assert "'lint'" in capsys.readouterr().err
    assert fetcher.resolved == ()

# --- the sync that follows ----------------------------------------------------------------------

def test_an_installer_that_could_not_be_started_exits_six_after_the_summary_went_out(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """uv missing and nothing refused: exit 6, the updated line on stdout, one line on stderr.

    Both streams are asserted whole, for `agl get`'s reason: with no refusal to join, the sync's 6
    is the whole answer, printed in the line `main` prints for any refusal that reaches it.
    """
    home = _home(tmp_path)
    _placed(home, "triage", _FLOWS)

    status = _main(
        home,
        "update",
        fetcher=_serving(FakeFetcher(), _FLOWS, "triage"),
        syncer=_uv_missing(home),
    )

    captured = capsys.readouterr()
    assert (status, captured.out, captured.err) == (
        6,
        "updated   triage  octo/flows/workflows/triage  0b496e9 -> f548e57\n",
        f"{_SAID_MISSING}\n",
    )

def test_a_refused_sync_with_no_environment_behind_it_exits_six_after_the_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The second rule: uv exiting non-zero with no venv yet has nothing to fall back on, so 6."""
    home = _home(tmp_path)
    fetcher = _moved(home)

    status = _main(home, "update", fetcher=fetcher, syncer=_uv_refusing(home))

    captured = capsys.readouterr()
    assert status == 6
    assert _words(captured.out)[0][:2] == ["updated", "moved"]
    assert captured.err.startswith(_SAID_REFUSED)
    assert captured.err.count(_UV_SAID.strip()) == 1

def test_a_refused_sync_over_an_environment_that_stood_warns_and_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The third rule: a venv stood before the sync, so uv's words go to stderr and that is all."""
    home = _home(tmp_path)
    fetcher = _moved(home)
    workspace_site_packages(home, SEGMENT).mkdir(parents=True)

    status = _main(home, "update", fetcher=fetcher, syncer=_uv_refusing(home))

    captured = capsys.readouterr()
    assert status == 0
    assert _words(captured.out)[0][:2] == ["updated", "moved"]
    assert captured.err.startswith(_WARNED)
    assert captured.err.count(_UV_SAID.strip()) == 1

@pytest.mark.parametrize(
    ("refusing", "installer", "said", "status", "reasons"),
    [
        pytest.param((_gone,), _uv_missing, _SAID_MISSING, 8, (_GONE,), id="a 3 and uv missing"),
        pytest.param(
            (_gone, _hollow),
            _uv_missing,
            _SAID_MISSING,
            8,
            (_GONE, _HOLLOW),
            id="a 3, a 2 and uv missing",
        ),
        pytest.param(
            (_gone,),
            _uv_refusing,
            _SAID_REFUSED,
            8,
            (_GONE,),
            id="a 3 and uv refusing with no venv",
        ),
        pytest.param(
            (_unanswered,),
            _uv_missing,
            _SAID_MISSING,
            6,
            (_UNANSWERED,),
            id="a 6 and uv missing",
        ),
    ],
)
def test_a_sync_failing_after_refusals_is_said_once_below_them_and_joins_their_status(
    tmp_path: Path,
    refusing: tuple[Callable[[AglHome, FakeFetcher], None], ...],
    installer: Callable[[AglHome], Syncer],
    said: str,
    status: int,
    reasons: tuple[str, ...],
) -> None:
    """`moved` is updated, the sync fails, and its 6 joins the refusals by `_refusal_status`.

    `agl get`'s case from `update`'s side, the refusals made in the comparison and the inspection:
    a 3 beside the sync exits 8, a 6 agrees with it, every reason is written once, and the sync's
    is written last, both streams counted.
    """
    home = _home(tmp_path)
    fetcher = _moved(home)
    for refused in refusing:
        refused(home, fetcher)

    exited, written = _written(home, "update", fetcher=fetcher, syncer=installer(home))

    assert exited == status
    assert written.count(said) == 1
    for reason in reasons:
        assert written.count(reason) == 1
        assert written.index(reason) < written.index(said)
    assert written.index("updated   moved") < written.index(said)

def test_a_copy_edited_meanwhile_and_a_sync_that_failed_after_it_exit_eight_together(
    tmp_path: Path,
) -> None:
    """The refusal made as a copy comes to be written (4) meets a sync that could not start (6).

    `lint` is updated, so the sync runs; `triage` was edited while its question was up, so it is
    refused `(not written)`. Its reason and the sync's are each written once, the sync's last.
    """
    home = _home(tmp_path)
    triage = _placed(home, "triage", _FLOWS)
    _changed(triage)
    _placed(home, "lint", _FLOWS)

    def editing_again(question: str) -> bool:
        _changed(triage)
        return True

    status, written = _written(
        home,
        "update",
        fetcher=_serving(FakeFetcher(), _FLOWS, "triage", "lint"),
        syncer=_uv_missing(home),
        confirm=editing_again,
    )

    edited = f"triage: {triage} changed after `agl update` measured it"
    assert status == 8
    assert written.count(edited) == 1
    assert written.count(_SAID_MISSING) == 1
    assert written.index(edited) < written.index(_SAID_MISSING)

def test_a_refusal_keeps_its_own_code_when_the_sync_after_it_only_warns(tmp_path: Path) -> None:
    """The third rule beside a refusal: the warning is written once, below it, and 3 stands."""
    home = _home(tmp_path)
    fetcher = _moved(home)
    _gone(home, fetcher)
    workspace_site_packages(home, SEGMENT).mkdir(parents=True)

    status, written = _written(home, "update", fetcher=fetcher, syncer=_uv_refusing(home))

    assert status == 3
    assert written.count(_WARNED) == 1
    assert written.count(_GONE) == 1
    assert written.index(_GONE) < written.index(_WARNED)
    assert "agl: " not in written

def test_refusals_with_nothing_placed_start_no_sync_and_exit_by_their_own_rule(
    tmp_path: Path,
) -> None:
    """A 3 and a 2 and nothing updated: 8, and `_NoSync`, which fails the test if asked, is not."""
    home = _home(tmp_path)
    fetcher = FakeFetcher()
    _gone(home, fetcher)
    _hollow(home, fetcher)

    assert _main(home, "update", fetcher=fetcher, syncer=_NoSync()) == 8

def test_a_sync_raising_something_unnamed_reaches_main_as_itself_with_its_traceback(
    tmp_path: Path,
) -> None:
    """No `AglError`, so nothing joins it: 70, with the traceback and the frame that raised it.

    For `agl get`'s reason, the traceback is what this asserts: a fold would answer 70 as well.
    """
    home = _home(tmp_path)
    fetcher = _moved(home)
    _gone(home, fetcher)

    status, written = _written(
        home, "update", fetcher=fetcher, syncer=_Raising(RuntimeError("the installer broke"))
    )

    assert status == 70
    assert "Traceback (most recent call last)" in written
    assert "RuntimeError: the installer broke" in written
    assert "`_Raising.sync`" in written
    assert written.count(_GONE) == 1

def test_a_refusal_raised_before_the_summary_leaves_the_command_as_itself_with_nothing_printed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A name `agl get` never placed is refused before anything is compared, let alone summarised.

    Through `main` it exits 3, and a command that folded it alone would exit 3 in the same words,
    so this calls the command itself: the refusal leaves as it was raised, and nothing is printed.
    """
    home = _home(tmp_path)
    hand_written = _workflow(home, "hand_written")
    parsed = _update_parser().parse_args(["hand_written"])

    with pytest.raises(NotFoundError) as refused:
        update_command.execute(
            home, parsed, fetcher=FakeFetcher(), syncer=_uv_missing(home), confirm=_asking_nothing
        )

    assert str(refused.value).startswith(f"{hand_written} holds no {PROVENANCE_FILE}")
    assert capsys.readouterr() == ("", "")

# --- the real fetcher, off this machine's network -----------------------------------------------

def test_the_real_fetcher_asks_a_stand_in_once_and_says_already_up_to_date(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Everything below the fetcher's own HTTP request is the code an operator runs.

    Two workflows at one repository and ref: one request, carrying the sha media type, and no
    request anywhere else - the codeload address handed over is one nothing listens on.
    """
    home = _home(tmp_path)
    _placed(home, "alpha", _RELEASED)
    _placed(home, "beta", _RELEASED)

    with GitHubApi() as api:
        api.resolves("octo", "flows", "release/1.0", _PLACED_FROM)
        fetcher = GitHubFetcher("http://127.0.0.1:9", api_url=api.url)
        status = _main(home, "update", fetcher=fetcher, syncer=_NoSync())
        seen = [(request.path, request.headers["accept"]) for request in api.requests]

    captured = capsys.readouterr()
    assert (status, captured.out, captured.err) == (0, "", _CURRENT)
    assert seen == [("/repos/octo/flows/commits/release/1.0", "application/vnd.github.sha")]

def test_the_real_fetcher_updates_a_workflow_from_both_stand_ins_at_the_ref_it_recorded(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One question about the ref and one download at that ref - never at the commit either named.

    The ref names `f548e57` when it is asked about and has moved on to `a5b1c2d` by the time it is
    downloaded, so the commit recorded is the one the archive says it holds. The ref is kept as
    it was written, the directory measures as its new provenance says, the executable bit
    survives, and `agl workflows` finds the workflow where it was put.
    """
    home = _home(tmp_path)
    entry = _placed(home, "triage", _RELEASED)
    files = {
        "workflows/triage/pyproject.toml": (_pyproject("triage"), False),
        "workflows/triage/__init__.py": (_MODULE_NOW, False),
        "workflows/triage/bin/run.sh": (b"#!/bin/sh\n", True),
    }

    with GitHubApi() as api, Codeload() as codeload:
        api.resolves("octo", "flows", "release/1.0", _NOW)
        body = archive(tree("flows-release-1.0", files), commit=_LATER)
        codeload.serves("octo", "flows", "release/1.0", body)
        status = _main(home, "update", fetcher=GitHubFetcher(codeload.url, api_url=api.url))
        asked = [request.path for request in api.requests]
        downloaded = [request.path for request in codeload.requests]

    assert status == 0
    assert asked == ["/repos/octo/flows/commits/release/1.0"]
    assert downloaded == ["/octo/flows/tar.gz/release/1.0"]
    assert capsys.readouterr().out == (
        "updated   triage  octo/flows/workflows/triage@release/1.0  0b496e9 -> a5b1c2d\n"
    )
    recorded = read_provenance(entry)
    assert recorded is not None
    assert (recorded.workflow.repository, recorded.commit) == (_RELEASED, _LATER)
    assert placed_hash(entry) == recorded.content_hash
    assert os.access(entry / "bin" / "run.sh", os.X_OK)
    assert _main(home, "workflows", fetcher=FakeFetcher()) == 0
    assert capsys.readouterr().out == "triage\n"

# --- what the command is, read off the module ---------------------------------------------------

def test_the_update_parser_takes_one_optional_positional_and_no_option_of_its_own() -> None:
    """No `--yes`, no `--force` and no token: public repositories only, and every question asked."""
    parser = _update_parser()

    options = {flag for action in parser._actions for flag in action.option_strings}
    positionals = [
        (action.dest, action.nargs) for action in parser._actions if not action.option_strings
    ]

    assert options == {"-h", "--help"}
    assert positionals == [("workflow", "?")]

def test_the_command_calls_exactly_one_api_function() -> None:
    """"Commands stay dumb" made mechanical - the same scan the other command suites make."""
    called = {
        node.attr
        for node in ast.walk(ast.parse(inspect.getsource(update_command)))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "api"
    }

    assert called == {"update"}

def test_the_command_never_asks_for_a_registered_repository(tmp_path: Path) -> None:
    """A workflow is updated in the workspace, which lives under no repository, as `agl get` is.

    `_never` on the `Invocation` is the instrument: calling `registered()` fails the test.
    """
    home = _home(tmp_path)
    _placed(home, "triage", _FLOWS)

    assert _main(home, "update", fetcher=_serving(FakeFetcher(), _FLOWS, "triage")) == 0
