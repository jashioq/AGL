"""Stage 10's walking skeleton, driven from the library side: `api.run` on `container.fakes()`.

Everything here runs on the all-fakes bundle - no network, no git, no process - which is measurable
target #8 and the reason every operation takes the bundle rather than building one. The workflows
are declared in this module and reached through hand-constructed `EntryPoint` values, exactly as
`tests/config/test_registry.py` and `tests/sdk/test_workflow.py` do: an entry point is a name, a
`module:attr` string and a group, so §3.3's registration line resolves without installing a package.
`workflows/noop/` is deliberately not used - it is deliverable 10.5 and does not exist yet.

**The `Stop` criterion is pinned by identity, not by class.** An `assert isinstance(...)` would pass
against an `api.run` that caught the workflow's `ReviewNotConverging`, threw it away and raised a
fresh one of the same class - which is the version of this bug worth catching, since the exit code
would still be 7 and the traceback would name this module instead of the step that stopped.

**The record is asserted field by field against §3.6**, key set included, because `run.json` is the
one value in AGL with no other copy anywhere. The `base_sha` assertions are the ones with teeth:
full length, and not the ref name - `refs/heads/main` would satisfy every "is a string" check.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Final

import pytest

from agl import api
from agl.config import container, registry
from agl.ports.errors import ConflictError, InputError, InternalError, NotFoundError, exit_code_for
from agl.ports.home_layout import RunScope
from agl.ports.ids import ProjectName, RunLabel
from agl.ports.run import JsonValue, RunSpec
from agl.ports.tree_layout import TreesRoot, run_branch
from agl.sdk.params import arg
from agl.sdk.workflow import Run, Stop, workflow

# `asyncio_mode = "strict"`, so every async test below carries its own marker.

PROJECT: Final = ProjectName("myapp")
LABEL: Final = RunLabel("auth")
SCOPE: Final = RunScope(PROJECT, LABEL)

# §3.6's `run.json`, key for key. Written out rather than read off `RunSpec`'s fields, because the
# published shape of the file is what this asserts and a record that agreed with itself would pass.
WIRE_KEYS: Final = frozenset(
    {"workflow", "workflow_version", "label", "base_ref", "base_sha", "branch", "params",
     "created_at"}
)


@dataclass(frozen=True)
class ProbeParams:
    """§3.3's example shape, which is also what `agl run probe -r "add oauth" -c 4` fills in."""

    request: str = arg("-r", "--request", help="what to build")
    concurrent: int = arg("-c", "--concurrent", default=3)


@dataclass(frozen=True)
class NoParams:
    """A workflow that takes nothing, and still has a params class to derive no flags from."""


class ReviewNotConverging(Stop):
    """§3.1's own example of a workflow's reason to stop, spelled against the SDK's `Stop`."""


# What each workflow was handed and what one of them raised, at module level because the workflows
# have to be: `EntryPoint.load` imports a module and reads an attribute in it, and sees no local.
handed: Final[list[Run[ProbeParams]]] = []
raised: Final[list[Stop]] = []


@workflow(name="probe", version="1.1", params=ProbeParams)
async def probe(run: Run[ProbeParams]) -> None:
    """Returns. The wiring probe stage 10 is about, with params it can be asserted on."""
    handed.append(run)


@workflow(name="halting", version="0.1", params=NoParams)
async def halting(run: Run[NoParams]) -> None:
    """Ends deliberately, with a reason of its own - which the framework must not rename."""
    stop = ReviewNotConverging("two rounds and no convergence")
    raised.append(stop)
    raise stop


def _point(name: str, attribute: str) -> EntryPoint:
    """§3.3's `probe = "agl.workflows.probe:probe"`, pointed at this module instead."""
    return EntryPoint(name=name, value=f"{__name__}:{attribute}", group=registry.GROUP)


POINTS: Final = (_point("probe", "probe"), _point("halting", "halting"))


def _fakes(tmp_path: Path) -> container.FakeServices:
    """Target #8's deployment: one repository seeded with a file, one store, one frozen clock."""
    return container.fakes(TreesRoot(tmp_path / "trees"), files={"src/a.txt": b"one\n"})


async def _record(harness: container.FakeServices) -> dict[str, JsonValue]:
    """The run's record, asserted present - every caller below is testing what is in it."""
    record = await harness.services.store.read_record(SCOPE)
    assert record is not None, "no run.json was written for this run"
    return record


async def _run(
    harness: container.FakeServices, name: str = "probe",
    argv: Sequence[str] = ("-r", "add oauth"), *, base_ref: str | None = None,
) -> None:
    """One invocation, with this module's entry points supplied instead of what is installed."""
    await api.run(harness.services, PROJECT, name, LABEL, argv, base_ref=base_ref, points=POINTS)


# --- a run that completes ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_workflow_that_returns_runs_to_completion(tmp_path: Path) -> None:
    """`agl run probe -n auth` end to end on fakes - the stage's first acceptance criterion."""
    handed.clear()
    harness = _fakes(tmp_path)

    await _run(harness)

    assert len(handed) == 1
    assert handed[0].services is harness.services


@pytest.mark.asyncio
async def test_the_record_holds_exactly_section_3_6s_fields(tmp_path: Path) -> None:
    """`run.json`'s published shape, key for key and value for value. `created_at` is the plan's own
    example moment because the fakes bundle's clock is frozen at it, and `concurrent` is a default
    the user never typed - `resume` takes no flags, so an unspoken one is lost if it is not here."""
    harness = _fakes(tmp_path)
    await _run(harness)
    record = await _record(harness)

    assert set(record) == WIRE_KEYS
    assert record["workflow"] == "probe"
    assert record["workflow_version"] == "1.1"
    assert record["label"] == "auth"
    assert record["branch"] == run_branch(LABEL) == "agl/auth"
    assert record["created_at"] == "2026-08-18T09:14:02Z"
    assert record["params"] == {"request": "add oauth", "concurrent": 3}
    # Written by AGL and read back by AGL: the record survives the round trip it exists for.
    assert RunSpec.from_json(record).label == LABEL


@pytest.mark.asyncio
async def test_the_base_sha_is_the_resolved_commit_and_not_the_ref_name(tmp_path: Path) -> None:
    """The pin (§3.6). An abbreviation is refused by `RunSpec`; a ref name would pin nothing."""
    harness = _fakes(tmp_path)
    history = harness.services.history
    default = await history.default_ref()
    resolved = await history.resolve(default)

    await _run(harness)
    record = await _record(harness)

    assert record["base_ref"] == default
    assert record["base_sha"] == resolved
    assert record["base_sha"] != record["base_ref"]
    assert isinstance(record["base_sha"], str)
    assert len(record["base_sha"]) in {40, 64}


@pytest.mark.asyncio
async def test_from_names_the_base_ref_and_the_default_is_the_repositorys(tmp_path: Path) -> None:
    """`--from <ref>` (§3.9). What the user said is kept; what it meant is resolved beside it."""
    harness = _fakes(tmp_path)

    await _run(harness, base_ref="main")
    record = await _record(harness)

    assert record["base_ref"] == "main"
    assert record["base_sha"] == await harness.services.history.resolve("main")


@pytest.mark.asyncio
async def test_a_completed_run_leaves_nothing_but_run_json(tmp_path: Path) -> None:
    """"No steps, no worktrees, no persistence beyond `run.json`" - stage 10, in as many words. The
    branch the record names is not created and no checkout is cut: `agl/<label>` arrives with the
    base worktree at 13.4, and a `run` that provisioned one here would be stage 13 leaking in."""
    harness = _fakes(tmp_path)
    await _run(harness)

    assert harness.repository.tip(run_branch(LABEL)) is None
    assert not (tmp_path / "trees").exists()


# --- params, and the two refusals the stage names ------------------------------------------------


@pytest.mark.asyncio
async def test_the_workflow_gets_its_dataclass_and_the_record_its_values(tmp_path: Path) -> None:
    """One chain: argv, the instance the workflow reads, and the mapping `run.json` holds."""
    handed.clear()
    harness = _fakes(tmp_path)

    await _run(harness, argv=["-r", "add oauth", "-c", "4"])

    assert handed[0].params == ProbeParams(request="add oauth", concurrent=4)
    assert isinstance(handed[0].params, ProbeParams)
    record = await _record(harness)
    assert record["params"] == {"request": "add oauth", "concurrent": 4}


@pytest.mark.asyncio
async def test_flags_the_workflow_refuses_stop_it_before_anything_runs(tmp_path: Path) -> None:
    """§3.3: validation failure is `InputError` -> exit 2, *before anything runs* - so no record."""
    handed.clear()
    harness = _fakes(tmp_path)

    with pytest.raises(InputError) as caught:
        await _run(harness, argv=[])

    assert exit_code_for(caught.value) == 2
    assert handed == []
    assert await harness.services.store.read_record(SCOPE) is None


@pytest.mark.asyncio
async def test_the_same_label_twice_is_refused_in_section_3_10s_words(tmp_path: Path) -> None:
    """The second acceptance criterion: exit 4, and the message the plan writes out. The refusal is
    here rather than in the command because §1.4's charge is precisely that commands did real work -
    and because a library caller needs the same answer as `agl run` does."""
    handed.clear()
    harness = _fakes(tmp_path)
    await _run(harness)

    with pytest.raises(ConflictError) as caught:
        await _run(harness)

    assert str(caught.value) == (
        "run 'auth' already exists - `agl resume auth` or `agl clear auth`."
    )
    assert exit_code_for(caught.value) == 4
    assert len(handed) == 1, "the refused run invoked the workflow anyway"


@pytest.mark.asyncio
async def test_an_unknown_workflow_name_is_a_not_found_and_records_nothing(tmp_path: Path) -> None:
    """The third: exit 3, from `config/registry.py`, before the store is touched at all."""
    harness = _fakes(tmp_path)

    with pytest.raises(NotFoundError) as caught:
        await _run(harness, name="nosuch")

    assert exit_code_for(caught.value) == 3
    assert "nosuch" in str(caught.value)
    assert await harness.services.store.read_record(SCOPE) is None


# --- the ordering hazard -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_stop_subclass_leaves_api_run_unwrapped_and_exits_seven(tmp_path: Path) -> None:
    """§3.1's stage-10 criterion: the *same object*, and 7 rather than 6 or 70. Identity is the
    assertion, not the class - see the module docstring. The last line is the other half of the
    order `run` is written in: the record is written before the workflow is invoked, so a stop or a
    crash leaves a run to resume or to clear, which is `Stop`'s own promise that results persist."""
    raised.clear()
    harness = _fakes(tmp_path)

    with pytest.raises(ReviewNotConverging) as caught:
        await _run(harness, name="halting", argv=[])

    assert caught.value is raised[0]
    assert exit_code_for(caught.value) == 7
    assert (await _record(harness))["workflow"] == "halting"


# --- the rest of the surface ---------------------------------------------------------------------


def test_list_workflows_is_the_registrys_sorted_names(tmp_path: Path) -> None:
    """§3.10's `agl workflows`, complete: 16.4 adds the command that prints this and nothing more.
    Sorted, so a listing is stable across environments rather than ordered by whatever sequence a
    metadata scan produced, and nothing is imported to answer it."""
    assert api.list_workflows(_fakes(tmp_path).services, points=POINTS) == ("halting", "probe")


@pytest.mark.asyncio
async def test_the_unbuilt_operations_name_their_deliverable(tmp_path: Path) -> None:
    """Declared so the CLI's dispatch is written against the whole surface, and refusing until
    built. `InternalError` - exit 70 - because at this stage no CLI verb reaches any of them, so a
    call is AGL's own bug rather than anything the caller supplied."""
    services = _fakes(tmp_path).services

    with pytest.raises(InternalError, match=r"16\.2"):
        await api.resume(services, PROJECT, LABEL)
    with pytest.raises(InternalError, match=r"16\.3"):
        await api.clear(services, PROJECT, LABEL)
    with pytest.raises(InternalError, match=r"16\.4"):
        await api.init(services)
