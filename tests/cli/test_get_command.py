"""`agl get <owner/repo/path[@ref]> ...`: the command, its summary, its streams and its exit status.

`api.get` decides; this command parses the arguments before anything is fetched, hands `api.get` a
printer for the summary, and turns the refusals into an exit status. `tests/test_get.py` holds the
phases themselves.

**The summary, with no colour to lean on.** The terminal port carries no styling and nothing in
`cli/` may import `rich`, so the first column is a word - `placed`, `declined` or `refused` - and a
line that is not `placed` ends in a few words saying why. A refusal's whole reason follows the
table, once per refusal: a download that failed refuses every workflow asked of it with one error,
and that reason is printed once, naming all of them.

**The streams.** A `placed` line goes to stdout, because it names a workflow the workspace now
holds; everything else is a note about one it does not, and goes to stderr with the questions.
`agl get ... | while read` sees the workflows it got and nothing else.

**The exit status.** A decline is the operator's answer, not a failure, so a command whose every
workflow was placed or declined exits 0 - under `< /dev/null` too, where every question is declined
and nothing is placed, which a script reads off an empty stdout. A refusal moves the status, and
several resolve by `cli/commands/__init__.py`'s `_refusal_status`: the code they share, or 8 where
they differ - never `exit_status`'s 70, which would say AGL broke. A sync that raises after the
placing exits 6 through `main`, the summary having gone out first.

**Every door out is substituted through `main.Invocation`**: the fetcher, the syncer and, where a
test answers for the operator, `confirm`. Where it does not, `sys.stdin` is replaced and the real
`confirm` reads it, as `tests/cli/test_confirm.py` does; nothing patches `builtins.input`. The real
fetcher runs once, against `instruments.codeload`'s stand-in on 127.0.0.1.
"""

import ast
import dataclasses
import inspect
import io
import os
import sys
import sysconfig
from collections.abc import Mapping
from pathlib import Path
from typing import Final
import pytest
from agl.adapters.github.fake import FakeFetcher
from agl.adapters.github.fetcher import GitHubFetcher
from agl.adapters.uv.fake import FakeSyncer
from agl.cli import main
from agl.cli.commands import _refusal_status
from agl.cli.commands import get as get_command
from agl.config import registry, sources
from agl.config.provenance import placed_hash, read_provenance
from agl.config.questions import Confirm
from agl.ports.errors import (
    AglError,
    InputError,
    NotFoundError,
    UpstreamUnavailable,
    UpstreamUnexpected,
)
from agl.ports.fetch import FetchedFile, Fetcher
from agl.ports.get_request import RepositoryAtRef
from agl.ports.home_layout import (
    AglHome,
    workflow_dir,
    workflows_dir,
    workspace_dir,
    workspace_pyproject,
    workspace_site_packages,
)
from agl.ports.ids import ProjectName, WorkflowName
from agl.ports.sync import Syncer, SyncOutcome
from agl.sdk._engine.services import Services
from agl.sdk.params import RefusingParser
from instruments.codeload import Codeload, archive, tree

# Never opened: `agl get` reads the home it is handed and no working directory.
ELSEWHERE: Final = Path("/nowhere")

TRIAGE: Final = WorkflowName("triage")

_REPOSITORY: Final = RepositoryAtRef("jashioq", "myrepo", None)
_NOWHERE: Final = RepositoryAtRef("octo", "nope", None)
_DOWN: Final = RepositoryAtRef("octo", "down", None)
_GARBLED: Final = RepositoryAtRef("octo", "garbled", None)

_SHA: Final = "7fd1a60b01f91b314f59955a4e4d4e80d8edf11d"

_MODULE: Final = b"from agl.sdk import Run, workflow\n"

_UV_SAID: Final = "error: no solution found for lint\n"

_HTTPX: Final = 'dependencies = ["httpx"]'

# The `lib/` subdirectory this interpreter installs into, which is the one a sync addresses.
SEGMENT: Final = Path(sysconfig.get_path("purelib")).parent.name

class Recording(Syncer):
    """A syncer answering yes, keeping each workspace it was handed and whether it was there."""

    def __init__(self) -> None:
        self.asked: list[Path] = []
        self.existed: list[bool] = []

    async def sync(self, workspace: Path) -> SyncOutcome:
        self.asked.append(workspace)
        self.existed.append(workspace.is_dir())
        return SyncOutcome(synced=True, status=0, output="")

class Raising(Syncer):
    """A syncer that raises what an adapter raises, so `main`'s one table answers for the class."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    async def sync(self, workspace: Path) -> SyncOutcome:
        raise self._error

def _never() -> tuple[ProjectName, Services]:
    raise AssertionError("`agl get` composed a repository")

def _home(tmp_path: Path) -> AglHome:
    """An AGL_HOME under `tmp_path` that is not there yet - what a first `agl get` meets."""
    return AglHome(tmp_path / "home")

def _pyproject(name: str, dependencies: str = "") -> bytes:
    return (
        f'[project]\nname = "{name}"\nversion = "0.1.0"\n{dependencies}\n'
        f'[project.entry-points."{registry.GROUP}"]\n{name} = "{name}:{name}"\n'
    ).encode()

def _serving(
    *names: str, depending: Mapping[str, str] | None = None, hollow: tuple[str, ...] = ()
) -> FakeFetcher:
    """`jashioq/myrepo` holding each named workflow under `workflows/`, and no `octo/nope` at all.

    `depending` maps a name to the dependency line its `[project]` table carries, which is what
    raises the question; a name in `hollow` holds no project file and is refused on inspection.
    """
    fetcher = FakeFetcher()
    files: dict[str, FetchedFile] = {}
    for name in names:
        written = _pyproject(name, (depending or {}).get(name, ""))
        files[f"workflows/{name}/pyproject.toml"] = FetchedFile(written)
        files[f"workflows/{name}/__init__.py"] = FetchedFile(_MODULE)
    for name in hollow:
        files[f"workflows/{name}/__init__.py"] = FetchedFile(_MODULE)
    fetcher.serves(_REPOSITORY, files)
    fetcher.refuses(_NOWHERE, NotFoundError("codeload has no public repository octo/nope"))
    return fetcher

def _standing(home: AglHome, name: str) -> Path:
    """A workflow already in the workspace, with a file only the operator's copy holds."""
    directory = workflows_dir(home) / name
    directory.mkdir(parents=True)
    (directory / "pyproject.toml").write_bytes(_pyproject(name))
    (directory / "__init__.py").write_bytes(b"# the operator's own\n")
    return directory

def _main(
    home: AglHome,
    *argv: str,
    fetcher: Fetcher | None = None,
    syncer: Syncer | None = None,
    confirm: Confirm | None = None,
) -> int:
    """One `agl` invocation reading `home`, with no repository behind it.

    `confirm` left out is the real one, reading whatever the test put on `sys.stdin`.
    """
    fetching = FakeFetcher() if fetcher is None else fetcher
    installer = FakeSyncer() if syncer is None else syncer

    def compose() -> main.Invocation:
        invocation = main.Invocation(
            registered=_never,
            settings=sources.resolve_settings(sources.Overrides(), {"AGL_HOME": str(home.path)}),
            cwd=ELSEWHERE,
            fetcher=lambda: fetching,
            syncer=lambda: installer,
        )
        return invocation if confirm is None else dataclasses.replace(invocation, confirm=confirm)

    return main.main(argv, compose=compose)

def _no(question: str) -> bool:
    return False

def _words(stream: str) -> list[list[str]]:
    """Each line split on whitespace, which is how a script reads a column."""
    return [line.split() for line in stream.splitlines()]

def _get_parser() -> RefusingParser:
    """The `get` subparser alone, built the way `main.parser()` builds it, for inspection."""
    root = RefusingParser(prog="agl", allow_abbrev=False)
    commands = root.add_subparsers(dest="command", required=True, parser_class=RefusingParser)
    return get_command.declare(commands)

# --- the arguments ------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "spec",
    [
        "jashioq",
        "jashioq/myrepo",
        "jashioq/myrepo/workflows/triage@",
        "jashioq/myrepo@v1.2.0/workflows/triage",
        "jashioq/myrepo/workflows/triage,,lint",
        "jashioq/myrepo/workflows/my-flow",
    ],
)
def test_an_argument_that_does_not_parse_exits_two_before_anything_is_fetched(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], spec: str
) -> None:
    """Exit 2 naming the argument, nothing asked of the fetcher, and AGL_HOME still absent.

    A ref written on the repository rather than last is one of these, and never a request for
    something else. The last argument parses as a path and names a directory that could never be
    imported as the workflow it would be placed as - refused by the same `WorkflowName` that
    `agl new` refuses it with. A later argument that is fine does not rescue an earlier one, since
    the request is one.
    """
    home = _home(tmp_path)
    fetcher = _serving("triage")

    assert _main(home, "get", "jashioq/myrepo/workflows/release", spec, fetcher=fetcher) == 2

    assert repr(spec) in capsys.readouterr().err
    assert fetcher.fetched == ()
    assert not home.path.exists()

def test_a_flag_a_get_line_does_not_declare_is_refused_before_anything_is_fetched(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = _home(tmp_path)
    fetcher = _serving("triage")

    assert _main(home, "get", "jashioq/myrepo/workflows/triage", "--force", fetcher=fetcher) == 2

    assert "--force" in capsys.readouterr().err
    assert fetcher.fetched == ()

# --- the summary and its streams ----------------------------------------------------------------

def test_a_placed_workflow_is_the_one_kind_of_line_that_goes_to_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Placed on stdout; declined, refused, the reasons and the questions all on stderr.

    One of each: `triage` stands already and the override is declined, `lint` declares a
    dependency and is approved, `release` asks nothing, `hollow` is refused on inspection and
    `octo/nope` is a repository the fetcher does not have.
    """
    home = _home(tmp_path)
    _standing(home, "triage")
    fetcher = _serving("triage", "lint", "release", depending={"lint": _HTTPX}, hollow=("hollow",))
    answers = iter([False, True])

    _main(
        home,
        "get",
        "jashioq/myrepo/workflows/triage,lint,release,hollow",
        "octo/nope/flows/stray",
        fetcher=fetcher,
        confirm=lambda question: next(answers),
    )

    captured = capsys.readouterr()
    assert _words(captured.out) == [
        ["placed", "lint", "jashioq/myrepo/workflows/lint"],
        ["placed", "release", "jashioq/myrepo/workflows/release"],
    ]
    assert _words(captured.err)[:3] == [
        ["declined", "triage", "jashioq/myrepo/workflows/triage", "(not", "overridden)"],
        ["refused", "stray", "octo/nope/flows/stray", "(not", "fetched)"],
        ["refused", "hollow", "jashioq/myrepo/workflows/hollow", "(not", "placeable)"],
    ]
    assert "stray: codeload has no public repository octo/nope" in captured.err
    assert "hollow: jashioq/myrepo/workflows/hollow holds no pyproject.toml" in captured.err

def test_the_summary_lines_its_columns_up_and_says_why_a_skipped_workflow_was_skipped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The layout as a person reads it: a marker column, a name column, the path, the few words.

    The marker is as wide as the widest word and the name as wide as the widest name in the whole
    summary, both streams counted, so the two streams line up where a terminal shows them as one.
    """
    home = _home(tmp_path)
    _standing(home, "triage")

    _main(
        home,
        "get",
        "jashioq/myrepo/workflows/triage,release",
        fetcher=_serving("triage", "release"),
        confirm=_no,
    )

    captured = capsys.readouterr()
    assert captured.out == "placed    release  jashioq/myrepo/workflows/release\n"
    assert captured.err == (
        "declined  triage   jashioq/myrepo/workflows/triage  (not overridden)\n"
    )

def test_a_workflow_at_a_ref_holding_a_slash_is_named_as_it_was_asked_for(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`release/1.0` written last, as a workflow's `uses:` writes it, and kept whole from there on.

    One fetch at that ref, a summary line spelling the workflow the way the argument did, and a
    provenance file recording the ref as it was written.
    """
    home = _home(tmp_path)
    released = RepositoryAtRef("jashioq", "myrepo", "release/1.0")
    fetcher = FakeFetcher()
    fetcher.serves(
        released,
        {
            "workflows/triage/pyproject.toml": FetchedFile(_pyproject("triage")),
            "workflows/triage/__init__.py": FetchedFile(_MODULE),
        },
    )

    status = _main(home, "get", "jashioq/myrepo/workflows/triage@release/1.0", fetcher=fetcher)

    assert status == 0
    assert [fetch.repository for fetch in fetcher.fetched] == [released]
    assert capsys.readouterr().out == (
        "placed    triage  jashioq/myrepo/workflows/triage@release/1.0\n"
    )
    recorded = read_provenance(workflow_dir(home, TRIAGE))
    assert recorded is not None
    assert recorded.workflow.repository == released

def test_a_declined_dependency_question_says_so_and_never_prints_a_dependency_raw(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`packaging` lets an escape through in a requirement's URL, and a terminal would act on one.

    The question shows each dependency as a literal and the summary names the question rather than
    the packages, so no byte of the declaration reaches either stream as itself.
    """
    home = _home(tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO("n\n"))
    escaped = 'dependencies = ["evil @ https://example.com/\\u001b[2J.whl"]'
    fetcher = _serving("lint", depending={"lint": escaped})

    assert _main(home, "get", "jashioq/myrepo/workflows/lint", fetcher=fetcher) == 0

    captured = capsys.readouterr()
    assert "(third-party dependencies)" in captured.err
    assert "\x1b" not in captured.err
    assert "\x1b" not in captured.out

# --- the exit status ----------------------------------------------------------------------------

def test_a_command_whose_every_workflow_was_placed_or_declined_exits_zero(tmp_path: Path) -> None:
    home = _home(tmp_path)
    _standing(home, "triage")

    status = _main(
        home,
        "get",
        "jashioq/myrepo/workflows/triage,release",
        fetcher=_serving("triage", "release"),
        confirm=_no,
    )

    assert status == 0
    assert workflow_dir(home, WorkflowName("release")).is_dir()

def test_with_stdin_closed_every_question_is_declined_and_the_command_still_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`< /dev/null`: the real `confirm` meets end of file at each question and takes it as no.

    Nothing is placed and nothing is refused, so the status is 0 and stdout is empty - which is
    how a script tells this apart from a command that placed what it asked for. The operator's own
    workflow is untouched, which is the point of answering no when nobody can be asked.
    """
    home = _home(tmp_path)
    standing = _standing(home, "triage")
    kept = (standing / "__init__.py").read_bytes()
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    status = _main(
        home,
        "get",
        "jashioq/myrepo/workflows/triage,lint",
        fetcher=_serving("triage", "lint", depending={"lint": _HTTPX}),
    )

    captured = capsys.readouterr()
    assert status == 0
    assert captured.out == ""
    assert captured.err.count("stdin was closed, and that is taken as no") == 2
    assert (standing / "__init__.py").read_bytes() == kept
    assert not workflow_dir(home, WorkflowName("lint")).exists()

def test_a_refusal_exits_with_its_own_code_once_everything_else_has_been_placed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit 3 for a repository that is not there, and the workflow that was there placed anyway."""
    home = _home(tmp_path)

    status = _main(
        home,
        "get",
        "jashioq/myrepo/workflows/release",
        "octo/nope/flows/stray",
        fetcher=_serving("release"),
    )

    assert status == 3
    assert _words(capsys.readouterr().out) == [
        ["placed", "release", "jashioq/myrepo/workflows/release"]
    ]

def test_one_failed_download_says_why_once_naming_every_workflow_it_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = _home(tmp_path)

    status = _main(home, "get", "octo/nope/flows/a,b,c", fetcher=_serving())

    err = capsys.readouterr().err
    assert status == 3
    assert err.count("codeload has no public repository octo/nope") == 1
    assert "a, b, c: codeload has no public repository octo/nope" in err

def test_two_refusals_of_different_classes_that_share_a_code_exit_with_that_code(
    tmp_path: Path,
) -> None:
    """Two downloads refused apart, one unanswered and one unreadable: two classes, one code, 6.

    Agreement is about the code a script reads and never about the class or the count, so a command
    that was refused one way twice does not read as one refused two ways.
    """
    home = _home(tmp_path)
    fetcher = FakeFetcher()
    fetcher.refuses(_DOWN, UpstreamUnavailable("codeload did not answer for octo/down"))
    fetcher.refuses(_GARBLED, UpstreamUnexpected("codeload answered octo/garbled unreadably"))

    status = _main(home, "get", "octo/down/flows/a", "octo/garbled/flows/b", fetcher=fetcher)

    assert status == 6

def test_refusals_that_disagree_exit_eight_rather_than_seventy_or_either_ones_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A repository that is not there is 3 and a download that is no workflow is 2, so: 8.

    Neither of theirs, since either would name one refusal and hide the other, and not 70, which
    says AGL broke where a command that goes on past each refusal has ended the way it is allowed
    to. 8 is the code for exactly this, so the reasons are the last lines written and no line
    explains the number.
    """
    home = _home(tmp_path)

    status = _main(
        home,
        "get",
        "octo/nope/flows/stray",
        "jashioq/myrepo/workflows/hollow",
        fetcher=_serving(hollow=("hollow",)),
    )

    written = capsys.readouterr().err.splitlines()
    assert status == 8
    assert written[-2] == "stray: codeload has no public repository octo/nope"
    assert written[-1].startswith("hollow: jashioq/myrepo/workflows/hollow holds no pyproject.toml")

@pytest.mark.parametrize(
    ("refusals", "status"),
    [
        ((), 0),
        ((NotFoundError("a"), NotFoundError("b")), 3),
        ((UpstreamUnavailable("a"), UpstreamUnexpected("b")), 6),
        ((NotFoundError("a"), InputError("b")), 8),
        ((NotFoundError("a"), InputError("b"), NotFoundError("c")), 8),
    ],
)
def test_refusals_exit_nought_when_there_are_none_their_shared_code_or_else_eight(
    refusals: tuple[AglError, ...], status: int
) -> None:
    """The rule on its own, no command around it: the answer is the refusals' and nothing else's.

    Handed once as a tuple and once as the one-pass iterator `execute` hands it, so a rule that read
    its argument twice would answer for nothing the second time.
    """
    assert _refusal_status(refusals) == status
    assert _refusal_status(iter(refusals)) == status

# --- the sync that follows ----------------------------------------------------------------------

def test_an_installer_that_could_not_be_started_exits_six_after_the_summary_went_out(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """uv missing: exit 6 through `main`, and the workflow it placed is on stdout regardless."""
    home = _home(tmp_path)

    status = _main(
        home,
        "get",
        "jashioq/myrepo/workflows/triage",
        fetcher=_serving("triage"),
        syncer=Raising(UpstreamUnavailable("uv is not installed, or 'uv' is not on PATH")),
    )

    captured = capsys.readouterr()
    assert status == 6
    assert _words(captured.out) == [["placed", "triage", "jashioq/myrepo/workflows/triage"]]
    assert "uv is not installed" in captured.err
    assert workflow_dir(home, TRIAGE).is_dir()

def test_a_refused_sync_with_no_environment_behind_it_exits_six_after_the_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """uv exiting non-zero on a workspace with no venv yet: nothing to fall back on, so exit 6."""
    home = _home(tmp_path)
    installer = FakeSyncer()
    installer.answers(workspace_dir(home), synced=False, status=2, output=_UV_SAID)

    status = _main(
        home, "get", "jashioq/myrepo/workflows/triage", fetcher=_serving("triage"), syncer=installer
    )

    captured = capsys.readouterr()
    assert status == 6
    assert _words(captured.out) == [["placed", "triage", "jashioq/myrepo/workflows/triage"]]
    assert "uv exited 2" in captured.err
    assert _UV_SAID.strip() in captured.err

def test_a_refused_sync_over_an_environment_that_stood_warns_and_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The third rule: a venv stood before the sync, so uv's words go to stderr and that is all."""
    home = _home(tmp_path)
    workspace_site_packages(home, SEGMENT).mkdir(parents=True)
    installer = FakeSyncer()
    installer.answers(workspace_dir(home), synced=False, status=2, output=_UV_SAID)

    status = _main(
        home, "get", "jashioq/myrepo/workflows/triage", fetcher=_serving("triage"), syncer=installer
    )

    captured = capsys.readouterr()
    assert status == 0
    assert _words(captured.out) == [["placed", "triage", "jashioq/myrepo/workflows/triage"]]
    assert "warning: the sync was refused" in captured.err
    assert _UV_SAID.strip() in captured.err

def test_a_home_that_is_not_there_yet_is_made_before_the_sync_is_handed_it(
    tmp_path: Path,
) -> None:
    """`agl get` on a machine with no AGL_HOME works as `agl new` does: made, placed, installed."""
    home = _home(tmp_path)
    syncer = Recording()

    status = _main(
        home, "get", "jashioq/myrepo/workflows/triage", fetcher=_serving("triage"), syncer=syncer
    )

    assert status == 0

    assert workspace_pyproject(home).is_file()
    assert syncer.asked == [workspace_dir(home)]
    assert syncer.existed == [True]

# --- the whole pipeline, off this machine's network ---------------------------------------------

def test_the_real_fetcher_against_a_stand_in_on_this_machine_places_what_agl_workflows_lists(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Parse, one download, inspection, placement, provenance and the listing that follows it.

    The archive is laid out as `git archive` lays one out - a pax header naming the commit, one
    top directory named for the ref asked - and served from 127.0.0.1, so everything below the
    fetcher's own HTTP request is the code an operator runs. What it checks is what nothing
    smaller can: that the commit the archive names is the one recorded, that the directory
    measures as recorded, that the executable bit survives, and that the registry finds the
    workflow where it was put.
    """
    home = _home(tmp_path)
    files = {
        "README.md": (b"# flows\n", False),
        "workflows/triage/pyproject.toml": (_pyproject("triage"), False),
        "workflows/triage/__init__.py": (_MODULE, False),
        "workflows/triage/bin/run.sh": (b"#!/bin/sh\n", True),
    }

    with Codeload() as codeload:
        codeload.serves("octo", "flows", "HEAD", archive(tree("flows-HEAD", files), commit=_SHA))
        status = _main(
            home, "get", "octo/flows/workflows/triage", fetcher=GitHubFetcher(codeload.url)
        )
        paths = [seen.path for seen in codeload.requests]

    assert status == 0
    assert paths == ["/octo/flows/tar.gz/HEAD"]
    directory = workflow_dir(home, TRIAGE)
    recorded = read_provenance(directory)
    assert recorded is not None
    assert recorded.commit == _SHA
    assert placed_hash(directory) == recorded.content_hash
    assert os.access(directory / "bin" / "run.sh", os.X_OK)
    assert not os.access(directory / "__init__.py", os.X_OK)
    assert capsys.readouterr().out == "placed    triage  octo/flows/workflows/triage\n"

    assert _main(home, "workflows") == 0
    assert capsys.readouterr().out == "triage\n"

# --- what the command is, read off the module ---------------------------------------------------

def test_the_get_parser_takes_one_or_more_positionals_and_no_option_of_its_own() -> None:
    """Workflows to fetch and nothing else: no `--yes`, and no token - public repositories only."""
    parser = _get_parser()

    options = {flag for action in parser._actions for flag in action.option_strings}
    positionals = [
        (action.dest, action.nargs) for action in parser._actions if not action.option_strings
    ]

    assert options == {"-h", "--help"}
    assert positionals == [("specs", "+")]

def test_the_command_calls_exactly_one_api_function() -> None:
    """"Commands stay dumb" made mechanical - the same scan the other command suites make."""
    called = {
        node.attr
        for node in ast.walk(ast.parse(inspect.getsource(get_command)))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "api"
    }

    assert called == {"get"}

def test_the_command_never_asks_for_a_registered_repository(tmp_path: Path) -> None:
    """A workflow is fetched into the workspace, which lives under no repository, like `agl new`.

    `_never` on the `Invocation` is the instrument: calling `registered()` fails the test.
    """
    home = _home(tmp_path)

    assert _main(home, "get", "jashioq/myrepo/workflows/triage", fetcher=_serving("triage")) == 0
