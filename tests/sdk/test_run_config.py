"""`run.config`: the project settings a workflow declared, and a refusal for every other key.

Driven through `api.run` both ways a run starts, because the declaration comes from two places. A
walked workspace reads it from the workflow's own `[tool.agl] config` line, so those tests build a
home with a `pyproject.toml` in it. Entry points handed over, which is what `agl.testing`'s harness
does, read no file, and the keys the bundle was built with are the declaration.

**The refusal is an `InputError` and never a `KeyError`.** `Mapping.get` and `in` are written over
`__getitem__` and catch `KeyError` alone, so a `KeyError` would come back as `None` or `False`. A
workflow would then send a prompt with a hole in it. Each of the three reads is asserted separately
for that reason: a mapping that refused `[]` and answered the other two would pass a test of `[]`.

**`run.services.config` is the same object.** `api.run` narrows the bundle before the workflow is
handed it, so there is no second route to a key the workflow did not declare.
"""

from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Final
import pytest
from agl import api, testing
from agl.config import container, registry
from agl.ports.errors import InputError, exit_code_for
from agl.ports.home_layout import AglHome, workflows_dir
from agl.ports.ids import ProjectName, RunLabel
from agl.ports.tree_layout import TreesRoot
from agl.sdk._workflow import Run, workflow

PROJECT: Final = ProjectName("myapp")
LABEL: Final = RunLabel("auth")

# What each workflow was handed, kept at module level because `EntryPoint.load` reads a module
# attribute and cannot see a local.
handed: Final[list[Run[object]]] = []
children: Final[list[Run[object]]] = []

@workflow
async def reading(run: Run) -> None:
    """Keeps the run, so a test can read its config once the walk has returned."""
    handed.append(run)

@workflow
async def branching(run: Run) -> None:
    """Opens one child and keeps both, so the child's config can be compared with the parent's."""
    handed.append(run)
    children.append(run.worktree("T-01"))

def _home(tmp_path: Path) -> AglHome:
    """An AGL_HOME nothing else can reach, built rather than resolved so no variable is read."""
    return AglHome(tmp_path / "home")

def _declared(home: AglHome, attribute: str, keys: str) -> Path:
    """One workflow directory whose `pyproject.toml` declares `keys`, pointed at this module."""
    directory = workflows_dir(home) / attribute
    directory.mkdir(parents=True)
    (directory / "pyproject.toml").write_text(
        f'[project]\nname = "{attribute}"\nversion = "0.1.0"\n\n'
        f'[project.entry-points."{registry.GROUP}"]\n{attribute} = "{__name__}:{attribute}"\n\n'
        f"[tool.agl]\nconfig = {keys}\n",
        encoding="utf-8",
    )
    return directory

async def _walked(tmp_path: Path, attribute: str, config: dict[str, str]) -> Path:
    """Run `attribute` from a workspace that declares `build` and `lint`, over `config`."""
    handed.clear()
    children.clear()
    home = _home(tmp_path)
    directory = _declared(home, attribute, '["build", "lint"]')
    fakes = container.fakes(TreesRoot(tmp_path / "trees"), config=config)
    await api.run(fakes.services, PROJECT, attribute, LABEL, (), home=home)
    return directory

def _point(attribute: str) -> EntryPoint:
    """A registration line for a workflow in this module, as the harness composes one."""
    return EntryPoint(name=attribute, value=f"{__name__}:{attribute}", group=registry.GROUP)

@pytest.mark.asyncio
async def test_a_declared_key_reads_exactly_the_value_the_project_file_holds(
    tmp_path: Path,
) -> None:
    await _walked(tmp_path, "reading", {"build": "./gradlew test", "lint": "ruff check"})

    config = handed[0].config

    assert config["build"] == "./gradlew test"
    assert config.get("lint") == "ruff check"
    assert "lint" in config

@pytest.mark.asyncio
async def test_a_declared_key_set_to_the_empty_string_reads_as_the_empty_string(
    tmp_path: Path,
) -> None:
    """Present-but-empty is present, and nothing is substituted for it on the way in."""
    await _walked(tmp_path, "reading", {"build": "", "lint": ""})

    assert handed[0].config["build"] == ""
    assert handed[0].config.get("lint") == ""

@pytest.mark.asyncio
async def test_iterating_the_config_yields_the_declared_keys_and_no_other_project_key(
    tmp_path: Path,
) -> None:
    """`secret` is in the project file and undeclared, so it is neither listed nor counted."""
    await _walked(tmp_path, "reading", {"build": "make", "lint": "", "secret": "hunter2"})

    config = handed[0].config

    assert list(config) == ["build", "lint"]
    assert len(config) == 2
    assert dict(config) == {"build": "make", "lint": ""}

@pytest.mark.asyncio
async def test_indexing_an_undeclared_key_refuses_naming_the_line_that_declares_it(
    tmp_path: Path,
) -> None:
    """Refused although the project file holds the key: the declaration decides, not the file."""
    directory = await _walked(tmp_path, "reading", {"build": "make", "lint": "", "secret": "x"})

    with pytest.raises(InputError) as refused:
        handed[0].config["secret"]

    said = str(refused.value)
    assert exit_code_for(refused.value) == 2
    assert said.startswith("the workflow 'reading' reads the project setting 'secret'")
    assert "declares build, lint and nothing else" in said
    line = '`config = ["build", "lint", "secret"]`'
    assert f"{line} in the [tool.agl] table of {directory / 'pyproject.toml'}" in said

@pytest.mark.asyncio
async def test_get_on_an_undeclared_key_refuses_rather_than_answering_none(tmp_path: Path) -> None:
    await _walked(tmp_path, "reading", {"build": "make", "lint": ""})

    with pytest.raises(InputError, match="reads the project setting 'secret'"):
        handed[0].config.get("secret")

@pytest.mark.asyncio
async def test_in_on_an_undeclared_key_refuses_rather_than_answering_false(
    tmp_path: Path,
) -> None:
    await _walked(tmp_path, "reading", {"build": "make", "lint": ""})

    with pytest.raises(InputError, match="reads the project setting 'secret'"):
        _ = "secret" in handed[0].config

@pytest.mark.asyncio
async def test_the_bundle_a_workflow_is_handed_offers_no_undeclared_key_either(
    tmp_path: Path,
) -> None:
    """`run.services` is public, so narrowing only `run.config` would leave a second way in."""
    await _walked(tmp_path, "reading", {"build": "make", "lint": "", "secret": "x"})

    run = handed[0]

    assert run.services.config is run.config
    with pytest.raises(InputError):
        run.services.config.get("secret")

@pytest.mark.asyncio
async def test_a_child_run_reads_the_same_config_as_the_run_that_cut_it(tmp_path: Path) -> None:
    await _walked(tmp_path, "branching", {"build": "make", "lint": "", "secret": "x"})

    parent, child = handed[0], children[0]

    assert child.config is parent.config
    assert dict(child.config) == {"build": "make", "lint": ""}
    with pytest.raises(InputError):
        child.config["secret"]

@pytest.mark.asyncio
async def test_a_run_handed_its_entry_points_declares_the_keys_its_bundle_was_built_with(
    tmp_path: Path,
) -> None:
    """No workspace, no `pyproject.toml`: the bundle's keys are the declaration, all of them."""
    handed.clear()
    fakes = container.fakes(TreesRoot(tmp_path / "trees"), config={"lint": ""})

    await api.run(fakes.services, PROJECT, "reading", LABEL, (), points=(_point("reading"),))

    assert dict(handed[0].config) == {"lint": ""}

@pytest.mark.asyncio
async def test_a_harness_run_reads_the_keys_its_config_declares_and_refuses_any_other(
    tmp_path: Path,
) -> None:
    handed.clear()
    harness = testing.harness(tmp_path, config={"lint": "ruff check"})

    await harness.run(reading)

    config = handed[0].config
    assert config["lint"] == "ruff check"
    with pytest.raises(InputError) as refused:
        config.get("build")
    assert "`agl.testing.harness(config=...)`" in str(refused.value)

@pytest.mark.asyncio
async def test_a_harness_built_without_config_declares_no_key_not_even_build(
    tmp_path: Path,
) -> None:
    """The real walk declares nothing a workflow did not write, so the harness default is empty."""
    handed.clear()
    harness = testing.harness(tmp_path)

    await harness.run(reading)

    assert len(handed[0].config) == 0
    with pytest.raises(InputError, match="declares no key"):
        handed[0].config["build"]
