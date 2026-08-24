"""Stage 10's walking skeleton, walked: `agl run noop -n x` through argv and the installed group.

`tests/test_api.py` proved the operations from the library side and `tests/cli/test_main.py` proved
the argv side, both against workflows those modules declare themselves. What neither could prove is
the *installation*: an `EntryPoint` a test constructs resolves without any package being installed,
so it says nothing about whether `pyproject.toml`'s `agl.workflows` table, the built
`entry_points.txt` and `registry.installed()` agree. This module is the one that asserts they do.

**Nothing here is a fixture-shaped stand-in.** The bundle is `container.fakes()` - target #8's no
network, no git, no process - handed in through `main`'s own `compose=` seam, and the invocation's
`points` is left at its default `None`, which is `registry.installed()`. So the workflow that runs
is the one an operator would get, reached the way `agl` reaches it, and the assertions below fail if
the editable install has gone stale against a `pyproject.toml` that has moved: refresh it with
`uv pip install -e . --no-deps`.

**`noop` is scaffolding and 19.4 deletes it**, this file with it. Nothing else in the suite may be
written against it.
"""

import asyncio
from pathlib import Path
from typing import Final

import pytest

from agl.cli import main
from agl.config import container, registry, sources
from agl.ports.home_layout import RunScope
from agl.ports.ids import ProjectName, RunLabel
from agl.ports.run import JsonValue, RunSpec
from agl.ports.tree_layout import TreesRoot, base_worktree, run_branch, run_trees_dir
from agl.sdk.workflow import Stop, Workflow
from agl.workflows.noop import AskedToStop, NoopParams, noop

# `agl init` is the one command that reads `settings` and `cwd`, and no invocation below is one -
# but neither field is optional (`cli/main.py` argues why), so both carry a real value nothing here
# looks at. `/nowhere` is absolute, which is the whole of what `AglHome` insists on, and no file
# under it is ever opened: `read_settings` treats a missing `config.toml` as a file that said
# nothing.
ELSEWHERE: Final = Path("/nowhere")
SETTINGS: Final = sources.resolve_settings(sources.Overrides(), {"AGL_HOME": str(ELSEWHERE)})


PROJECT: Final = ProjectName("myapp")
LABEL: Final = RunLabel("x")
SCOPE: Final = RunScope(PROJECT, LABEL)

# §3.6's `run.json`, key for key, written out rather than read off `RunSpec` for
# `tests/test_api.py`'s reason: a record that agreed with itself would pass either way.
WIRE_KEYS: Final = frozenset(
    {"workflow", "workflow_version", "label", "base_ref", "base_sha", "branch", "params",
     "created_at"}
)

# The reason `--stop` carries in every test below, and the one string this module tracks from argv
# to stdout: a person types it, `sdk/params.py` parses it, the workflow raises with it, and
# `cli/main.py` prints it. Nothing in the framework knows what it says.
REASON: Final = "nothing to do here"


def _fakes(tmp_path: Path) -> container.FakeServices:
    """Target #8's deployment: one seeded repository, one store, one frozen clock."""
    return container.fakes(TreesRoot(tmp_path / "trees"), files={"src/a.txt": b"one\n"})


def _compose(harness: container.FakeServices) -> main.Compose:
    """`main`'s seam, filled in - and `points` deliberately left `None`.

    That default is `registry.installed()`, so the name `noop` on the command line is resolved
    against the real `agl.workflows` entry-point group rather than against anything this module
    built. The fakes bundle substitutes the *ports*; the registry is not substituted at all.

    `registered` is a callable since 11.0, §3.10's composition being per-command, and here it is one
    that answers out of a local rather than by resolving a repository - which is why none of this
    needs a git checkout to reach the installed workflow.
    """
    return lambda: main.Invocation(
        registered=lambda: (PROJECT, harness.services), settings=SETTINGS, cwd=ELSEWHERE
    )


def _main(harness: container.FakeServices, *flags: str) -> int:
    """`agl run noop -n x [flags]`, through the real parser, dispatch and top-level handler."""
    return main.main(("run", "noop", "-n", str(LABEL), *flags), compose=_compose(harness))


def _record(harness: container.FakeServices) -> dict[str, JsonValue]:
    """The run's record, asserted present. `run.json` is the only thing stage 10 persists."""
    record = asyncio.run(harness.services.store.read_record(SCOPE))
    assert record is not None, "no run.json was written for this run"
    return record


# --- the wiring, end to end ----------------------------------------------------------------------


def test_agl_run_noop_exits_zero_through_the_installed_entry_point(tmp_path: Path) -> None:
    """Stage 10's first acceptance criterion, in the words it is written in.

    The record is asserted too, because exit 0 would also be true of a `main` that parsed the line
    and did nothing: `run.json` is the evidence that the name reached the registry, the registry
    reached this package, and `api.run` ran before the workflow did.
    """
    harness = _fakes(tmp_path)

    assert _main(harness) == 0

    assert _record(harness)["workflow"] == "noop"


def test_the_record_holds_section_3_6s_fields_with_a_full_length_base_sha(tmp_path: Path) -> None:
    """`run.json`'s published shape, for the run an operator's own invocation would write.

    The `base_sha` assertions are the ones with teeth: §3.6 requires "a full 40- or 64-character
    object name", pinning the resolved commit rather than the ref name, because a commit landing on
    the base branch between run and resume would otherwise move the first step's starting head. A
    ref name would satisfy every "is a string" check.
    """
    harness = _fakes(tmp_path)
    assert _main(harness) == 0

    record = _record(harness)

    assert set(record) == WIRE_KEYS
    assert record["workflow"] == "noop"
    assert record["workflow_version"] == "1"
    assert record["label"] == "x"
    assert record["branch"] == run_branch(LABEL) == "agl/x"
    assert record["params"] == {"stop": ""}
    assert record["base_ref"] == asyncio.run(harness.services.history.default_ref())
    assert record["base_sha"] != record["base_ref"]
    assert isinstance(record["base_sha"], str)
    assert len(record["base_sha"]) in {40, 64}
    # Written by AGL and read back by AGL: the record survives the round trip it exists for.
    assert RunSpec.from_json(record).label == LABEL


def test_the_same_label_a_second_time_exits_four(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The stage's second criterion. The refusal is `api.run`'s and reaches the user unchanged."""
    harness = _fakes(tmp_path)
    assert _main(harness) == 0
    capsys.readouterr()

    assert _main(harness) == 4

    assert capsys.readouterr().err == (
        "agl: run 'x' already exists - `agl resume x` or `agl clear x`.\n"
    )


def test_a_completed_run_leaves_its_own_base_and_nothing_more(tmp_path: Path) -> None:
    """`noop` builds nothing, which is the whole of what it is for.

    "No steps, no persistence beyond `run.json`" is stage 10 in as many words and this workflow adds
    nothing to it. What *is* under the trees root belongs to `api.run` and not to the workflow: 13.4
    provisions the run's own `_base` from the pinned `base_sha` before any workflow function is
    entered, so §3.9's "`agl/<label>` is a real ref from run start" holds even for the run that does
    the least work of any run AGL can perform. Until 13.4 this test asserted the opposite and named
    stage 13 as what would change it.

    The claim about *this workflow* is therefore the last assertion, and it is the one that would
    catch `noop` growing a step or a child: one checkout under `.trees/x/`, the run's own.
    """
    harness = _fakes(tmp_path)

    assert _main(harness) == 0

    trees = TreesRoot(tmp_path / "trees")
    assert harness.repository.tip(run_branch(LABEL)) == _record(harness)["base_sha"]
    assert base_worktree(trees, LABEL).is_dir()
    assert sorted(place.name for place in run_trees_dir(trees, LABEL).iterdir()) == ["_base"]


# --- the flag, and the `Stop` it can raise -------------------------------------------------------


def test_stop_exits_seven_with_the_reason_on_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The stage's remaining criterion: **a raised `Stop` exits 7, not 6 or 70** (§3.1).

    `AskedToStop` appears in no table - `exit_code_for` walks the MRO to `Stop` - and it is rendered
    on stdout with no `agl:` prefix, because a run that ended deliberately did not fail. Both halves
    are asserted: the number is what a script branches on, and the stream is what fails if
    `cli/main.py`'s two `except` clauses are ever swapped.
    """
    harness = _fakes(tmp_path)

    assert _main(harness, "--stop", REASON) == 7

    captured = capsys.readouterr()
    assert captured.out == f"stopped: {REASON}\n"
    assert captured.err == "", "a deliberate end was reported as a failure"


def test_the_flags_value_reaches_the_workflow_and_the_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """§3.3's `arg()` end to end, on the short spelling: argv, `run.params`, and `run.json`.

    The reason on stdout is the arrival proof that no store read could give. Nothing between the
    command line and this workflow knows that string, and the only thing that can put it on stdout
    is `noop` raising `AskedToStop` with `run.params.stop` - so reading it back out of the process
    means the parsed dataclass reached the function. The record is the other half: §3.3 persists
    params into `run.json`, "which is why `agl resume auth` takes no flags".
    """
    harness = _fakes(tmp_path)

    assert _main(harness, "-s", REASON) == 7

    assert capsys.readouterr().out == f"stopped: {REASON}\n"
    assert _record(harness)["params"] == {"stop": REASON}


def test_the_stop_reason_is_this_workflows_own_class_and_not_the_frameworks() -> None:
    """§3.1: "`Stop` is the framework's terminal-end mechanism and carries no domain vocabulary.
    Workflows subclass it under their own names." `AskedToStop` is `noop`'s, and it is a subclass
    rather than `Stop` itself so that the class carries the fact and the message carries the
    reason. Asserted here rather than through the CLI because the exit code cannot see it: 7 is
    `Stop`'s row in the one table, and a workflow raising the base class would score the same."""
    assert issubclass(AskedToStop, Stop)
    assert AskedToStop is not Stop


# --- the installed group -------------------------------------------------------------------------


def test_noop_is_loadable_through_the_real_entry_point_group() -> None:
    """§3.3's registration, resolved the way `api.run` resolves it: `registry.installed()`.

    `Workflow[object]` on the left is load-bearing and is `api.py`'s own line - a bare generic class
    in `type[T]` position infers `Workflow[Any]`, PEP 696 default notwithstanding, and the `Any`
    stops at the annotation. Identity is the assertion: an equal-looking object would pass anything
    weaker, and what is being claimed is that `pyproject.toml`'s one line resolves to *this*
    module's `noop` and not to something that merely looks like a workflow.
    """
    wf: Workflow[object] = registry.load(registry.installed(), "noop", Workflow)

    assert wf.name == "noop"
    assert wf.version == "1"
    assert wf.params is NoopParams
    loaded: object = wf
    assert loaded is noop, "the agl.workflows entry point resolved to something else"
