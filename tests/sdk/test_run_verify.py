"""What `run.verify` promises: the command, as written, run in this run's own checkout.

The route a workflow had before this verb was `run.services.workspaces.open(label, None, base)` and
then `run.services.verifier.verify(command, place.path)`. From a child that address is the root's
`_base`, and nothing raises, so a child gating its own work gated its parent's tree instead. The
first two tests are that defect closed from each side, and they are asserted against a recording
verifier because `FakeVerifier` ignores `workdir` and would pass against the old route as well.

**What a verification is not is the other half of this file.** It reads no project setting, so a
workflow declaring nothing can still verify; it passes `""` through; and it hands back the
verifier's own outcome, a failing one included, rather than raising. It does write an entry, under
the `Run` that ran it, and `test_verify_record.py` holds what a resume does with one. The real-git
test at the bottom pins what is left of the old price: a verify with no recorded outcome runs, and
a step replayed from the ledger does not touch the checkout, so it runs on the checkout as it
stands, which can be past the head the ledger replayed.
"""

import subprocess
from dataclasses import replace
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Final
import pytest
from agl import api
from agl.adapters.claude_code.fake import Conversation, Script
from agl.adapters.filesystem.store import FilesystemStore
from agl.adapters.git.history import GitHistory
from agl.adapters.git.workspace import GitWorkspaceProvider
from agl.adapters.shell.verifier import ShellVerifier
from agl.config import container, registry
from agl.ports.agent import AgentOutcome, Claude, Restriction, StopReason
from agl.ports.errors import InputError, exit_code_for
from agl.ports.home_layout import AglHome, RunScope
from agl.ports.ids import Namespace, ProjectName, RunLabel
from agl.ports.tree_layout import TreesRoot
from agl.ports.verifier import Verifier, VerifierOutcome
from agl.sdk._engine.services import Services
from agl.sdk._workflow import Run, workflow
from agl.sdk.roles import Role, role

PROJECT: Final = ProjectName("myapp")
LABEL: Final = RunLabel("auth")
SCOPE: Final = RunScope(PROJECT, LABEL)
CHILD: Final = "T-01"

RED: Final = VerifierOutcome(passed=False, status=3, output="2 tests failed\n")

class _Recording(Verifier):
    """Every command it was handed and the directory each was run in, answering one outcome."""

    def __init__(self, answer: VerifierOutcome = RED) -> None:
        self.calls: list[tuple[str, Path]] = []
        self.standing: list[bool] = []
        self.answer = answer

    async def verify(self, command: str, workdir: Path) -> VerifierOutcome:
        self.calls.append((command, workdir))
        self.standing.append(workdir.is_dir())
        return self.answer

# What each workflow was handed back, kept at module level because `EntryPoint.load` reads a module
# attribute and cannot see a local.
verdicts: Final[list[VerifierOutcome]] = []

COMMAND: Final = "./gradlew test"

@workflow
async def from_the_root(run: Run) -> None:
    """Verifies once from the run itself."""
    verdicts.append(await run.verify(COMMAND))

@workflow
async def from_a_child(run: Run) -> None:
    """Opens one child, takes no step in it, and verifies from there."""
    verdicts.append(await run.worktree(CHILD).verify(COMMAND))

@workflow
async def with_nothing_to_run(run: Run) -> None:
    """Verifies the empty command, which is a value."""
    verdicts.append(await run.verify(""))

@workflow
async def with_no_text(run: Run) -> None:
    """Hands a child's verify something that is not a string, as an untyped caller could."""
    unchecked: object = None
    verdicts.append(await run.worktree(CHILD).verify(unchecked))  # type: ignore[arg-type]

def _point(attribute: str) -> EntryPoint:
    """A registration line for a workflow in this module, as the harness composes one."""
    return EntryPoint(name=attribute, value=f"{__name__}:{attribute}", group=registry.GROUP)

async def _ran(tmp_path: Path, attribute: str, gate: Verifier) -> container.FakeServices:
    """Run `attribute` over fakes declaring no project setting, with `gate` as the verifier."""
    verdicts.clear()
    fakes = container.fakes(TreesRoot(tmp_path / "trees"), config={})
    services = replace(fakes.services, verifier=gate)
    await api.run(services, PROJECT, attribute, LABEL, (), points=(_point(attribute),))
    return fakes

@pytest.mark.asyncio
async def test_a_child_run_verifies_in_its_own_checkout_and_never_in_the_runs_base(
    tmp_path: Path,
) -> None:
    gate = _Recording()

    await _ran(tmp_path, "from_a_child", gate)

    assert gate.calls == [(COMMAND, tmp_path / "trees" / str(LABEL) / CHILD)], (
        "the child's verification ran somewhere other than the child's own checkout - the "
        "`_base` address is the root's, and a child gating there gates work that is not its own"
    )

@pytest.mark.asyncio
async def test_the_root_run_verifies_in_the_base_checkout_the_walk_opened(tmp_path: Path) -> None:
    gate = _Recording()

    await _ran(tmp_path, "from_the_root", gate)

    assert gate.calls == [(COMMAND, tmp_path / "trees" / str(LABEL) / "_base")]

@pytest.mark.asyncio
async def test_the_outcome_handed_back_is_the_verifiers_own_and_a_failure_does_not_raise(
    tmp_path: Path,
) -> None:
    """A failing command is a verdict and not an exception - the port's own promise, passed on."""
    gate = _Recording(RED)

    await _ran(tmp_path, "from_the_root", gate)

    assert verdicts == [RED]
    assert verdicts[0] is gate.answer

@pytest.mark.asyncio
async def test_an_empty_command_reaches_the_verifier_unchanged_with_nothing_put_in_its_place(
    tmp_path: Path,
) -> None:
    gate = _Recording(VerifierOutcome(passed=True, status=0, output=""))

    await _ran(tmp_path, "with_nothing_to_run", gate)

    assert [command for command, _ in gate.calls] == [""]

@pytest.mark.asyncio
async def test_a_workflow_declaring_no_project_setting_still_verifies_a_command_it_chose(
    tmp_path: Path,
) -> None:
    """`verify` reads no key, so a bundle with no `build` in it is no refusal here, unlike
    `integrate()`: the command is the workflow's argument and the project file is not consulted."""
    gate = _Recording()

    await _ran(tmp_path, "from_a_child", gate)

    assert len(gate.calls) == 1

@pytest.mark.asyncio
async def test_a_command_that_is_not_a_string_is_refused_before_a_checkout_is_opened(
    tmp_path: Path,
) -> None:
    """`asyncio.create_subprocess_shell` raises a bare `ValueError` on `None`, which leaves on 70 as
    AGL's own bug. The refusal is an `InputError` instead, and it lands before the child is cut."""
    gate = _Recording()

    with pytest.raises(InputError) as refused:
        await _ran(tmp_path, "with_no_text", gate)

    assert exit_code_for(refused.value) == exit_code_for(InputError)
    assert "`run.verify`" in str(refused.value)
    assert gate.calls == []
    assert not (tmp_path / "trees" / str(LABEL) / CHILD).exists()

@pytest.mark.asyncio
async def test_a_child_that_only_verified_has_its_checkout_given_back_when_the_run_finishes(
    tmp_path: Path,
) -> None:
    """Verifying from a child that took no step cuts that child's checkout, as its first step would,
    and the teardown that releases a finished run's checkouts has to reach that one too."""
    gate = _Recording()

    fakes = await _ran(tmp_path, "from_a_child", gate)

    assert gate.standing == [True], "the child's checkout was not there when the command ran in it"
    assert not (tmp_path / "trees" / str(LABEL) / CHILD).exists()
    assert fakes.repository.tip(f"agl/_work/{LABEL}/{CHILD}") is None

@pytest.mark.asyncio
async def test_a_verification_writes_an_entry_on_the_ledger_under_the_child_that_ran_it(
    tmp_path: Path,
) -> None:
    fakes = await _ran(tmp_path, "from_a_child", _Recording())

    assert await fakes.store.namespaces(SCOPE) == (Namespace(CHILD),)

# --- real git and a real shell ------------------------------------------------------------------

SEEDED: Final = "README.md"

@role(model=Claude.SONNET)
def _writer(name: str) -> Role[None]:
    """A role whose agent writes one file named after the step, reporting through no tool."""
    return Role(
        name=name, instructions=f"write {name}", restrictions=set[Restriction](), tools=()
    )

def _git(cwd: Path, *argv: str) -> str:
    """Run git for the fixture and the assertions, raw, so no adapter answers for itself."""
    return subprocess.run(
        ["git", *argv], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout

@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real repository with one commit, and no configuration from this machine."""
    for name in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"):
        monkeypatch.setenv(name, str(tmp_path / "nonexistent-git-config"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for identity in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{identity}_NAME", "AGL verify")
        monkeypatch.setenv(f"GIT_{identity}_EMAIL", "agl@example.invalid")
    work = tmp_path / "repo"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    (work / SEEDED).write_bytes(b"seed\n")
    _git(work, "add", SEEDED)
    _git(work, "commit", "-q", "-m", "the state a run is cut from")
    return work

def _writes() -> Script:
    """An agent that writes a file named for its instructions into the checkout and stops."""

    async def _script(conversation: Conversation) -> AgentOutcome:
        said = conversation.task.instructions
        (conversation.task.workspace / said.replace(" ", "-")).write_text(said)
        return AgentOutcome(stop_reason=StopReason.COMPLETED, text="")

    return _script

def _real(repository: Path, tmp_path: Path) -> Services:
    """Real git, a real ledger and a real shell, over the fakes' agent and terminal."""
    trees = TreesRoot(tmp_path / "trees")
    fakes = container.fakes(trees, config={}, claude=_writes())
    return replace(
        fakes.services,
        store=FilesystemStore(AglHome(tmp_path / "home")),
        workspaces=GitWorkspaceProvider(repository, trees),
        history=GitHistory(repository),
        verifier=ShellVerifier(),
    )

async def _walk(services: Services, base: str) -> Run[None]:
    """One root `Run` with its `_base` opened first, as `api._walk` opens it. A second call over the
    same services is a resume: the same ledger, the same checkout, a fresh ordinal count."""
    await services.workspaces.open(LABEL, None, base)
    return Run(params=None, services=services, scope=SCOPE, base=base)

@pytest.mark.asyncio
async def test_a_real_shell_run_from_a_child_prints_the_childs_checkout_as_its_directory(
    repository: Path, tmp_path: Path
) -> None:
    services = _real(repository, tmp_path)
    run = await _walk(services, _git(repository, "rev-parse", "HEAD").strip())

    verdict = await run.worktree(CHILD).verify("pwd -P")

    assert verdict.passed
    assert Path(verdict.output.strip()) == (tmp_path / "trees" / str(LABEL) / CHILD).resolve()

@pytest.mark.asyncio
async def test_a_verify_with_no_recorded_outcome_runs_on_the_checkout_as_it_stands(
    repository: Path, tmp_path: Path
) -> None:
    """What a verify costs where the record holds no outcome for it, as a record from before
    verifies were recorded holds none.

    The first walk commits twice and verifies nothing. The second replays the first step, which
    leaves the checkout where the first walk left it, and verifies: the command runs, and sees the
    second commit, not the first.
    """
    services = _real(repository, tmp_path)
    base = _git(repository, "rev-parse", "HEAD").strip()
    first = await _walk(services, base)
    await first.step(_writer("one"), commit="one")
    after_one = _git(tmp_path / "trees" / str(LABEL) / "_base", "rev-parse", "HEAD").strip()
    await first.step(_writer("two"), commit="two")
    after_two = _git(tmp_path / "trees" / str(LABEL) / "_base", "rev-parse", "HEAD").strip()

    resumed = await _walk(services, base)
    await resumed.step(_writer("one"), commit="one")
    verdict = await resumed.verify("git rev-parse HEAD")

    assert after_one != after_two
    assert verdict.output.strip() == after_two
