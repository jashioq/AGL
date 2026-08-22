"""What the settings types promise: the plan's fields, per-connector nesting, and no defaults.

Three of these tests are about absences, which is unusual enough to say why. `Project` holding
exactly five fields, `AgentSettings` holding exactly one section per `Provider`, and no field
anywhere carrying a default are each a rule the module states in prose, and each is the kind of
rule a later stage breaks by *adding* something reasonable - a sixth project field, a shared
connector type, a `cli_path: Path | None = None` that looks like a convenience. Prose does not
notice; these do.

The no-default rule is checked twice on purpose. `dataclasses.fields` proves it of every field
mechanically, including any field added tomorrow. The `TypeError` assertions prove the consequence
the module actually relies on: a construction that omits a value fails before `__post_init__` runs,
so `sources.py` cannot resolve three precedence layers and silently inherit a fourth from here.

Nothing below touches the filesystem, and the paths are deliberately fictional: these constructors
are pure functions of their arguments, so a test that needed a real directory would be testing
something this module promised not to do.
"""

from dataclasses import MISSING, FrozenInstanceError, fields
from math import inf, nan
from pathlib import Path
from typing import Final

import pytest

from agl.config.schema import AgentSettings, ClaudeSettings, OpenAiSettings, Project, Settings
from agl.ports.agent import Provider
from agl.ports.errors import InputError
from agl.ports.home_layout import AglHome
from agl.ports.ids import ProjectName
from agl.ports.tree_layout import TreesRoot

_CLAUDE: Final = ClaudeSettings(enabled=True, cli_path=None)
_OPENAI: Final = OpenAiSettings(enabled=False, cli_path=Path("/opt/harness/bin/agent"))
_AGENTS: Final = AgentSettings(claude=_CLAUDE, openai=_OPENAI)
_SETTINGS: Final = Settings(home=AglHome(Path("/agl-home")), agents=_AGENTS)
_PROJECT: Final = Project(
    name=ProjectName("myapp"),
    repo=Path("/Users/jan/dev/myapp"),
    trees=TreesRoot(Path("/Users/jan/dev/.agl-trees/myapp")),
    build="./gradlew build",
    build_timeout=600,
)


# --- The shapes -------------------------------------------------------------------------------


def test_a_project_holds_exactly_the_five_fields_the_plan_writes_into_the_file() -> None:
    """§3.10 prints that file in full. A sixth field is a sixth thing every project answers for."""
    assert tuple(field.name for field in fields(Project)) == (
        "name",
        "repo",
        "trees",
        "build",
        "build_timeout",
    )
    assert _PROJECT.name == ProjectName("myapp")
    assert _PROJECT.repo == Path("/Users/jan/dev/myapp")
    assert _PROJECT.trees == TreesRoot(Path("/Users/jan/dev/.agl-trees/myapp"))
    assert _PROJECT.build == "./gradlew build"
    assert _PROJECT.build_timeout == 600


def test_settings_holds_the_home_and_the_agent_sections_and_nothing_from_a_project() -> None:
    """`agl init` and `agl workflows` construct this where no project file exists yet."""
    assert tuple(field.name for field in fields(Settings)) == ("home", "agents")
    assert _SETTINGS.home == AglHome(Path("/agl-home"))
    assert _SETTINGS.agents is _AGENTS


def test_there_is_one_agent_section_per_provider_member() -> None:
    """§1.10's fix: a provider with no section is a provider nothing can configure."""
    assert {field.name for field in fields(AgentSettings)} == {str(one) for one in Provider}
    assert _SETTINGS.agents.claude is _CLAUDE
    assert _SETTINGS.agents.openai is _OPENAI


def test_the_two_connector_sections_are_distinct_types_neither_derived_from_the_other() -> None:
    """One type reused would grow a field its sibling has no meaning for. Two cannot.

    Both operands are widened to `object` deliberately. Compared at their own types, `mypy
    --strict` refuses the expression outright - *non-overlapping equality check* - which is a
    stronger statement of this test's claim than the assertion is, and one that holds at every
    call site rather than only here. What is left to check at runtime is that two sections built
    from identical values are still not equal, since dataclass equality across unrelated classes
    is a thing a shared base class would quietly turn on.
    """
    assert not issubclass(ClaudeSettings, OpenAiSettings)
    assert not issubclass(OpenAiSettings, ClaudeSettings)
    assert len({ClaudeSettings, OpenAiSettings}) == 2
    claude: object = ClaudeSettings(enabled=True, cli_path=None)
    openai: object = OpenAiSettings(enabled=True, cli_path=None)
    assert claude != openai, "identical values in two sections are still not interchangeable"


# --- No defaults, and the consequence the module relies on --------------------------------------


def test_no_field_on_any_of_these_types_carries_a_default() -> None:
    """A default here would be a precedence layer `sources.py` never composed and cannot see."""
    for holder in (ClaudeSettings, OpenAiSettings, AgentSettings, Settings, Project):
        for field in fields(holder):
            assert field.default is MISSING, f"{holder.__name__}.{field.name} has a default"
            assert field.default_factory is MISSING, (
                f"{holder.__name__}.{field.name} has a default factory"
            )


def test_omitting_any_value_is_a_TypeError_rather_than_a_quietly_supplied_one() -> None:
    """The rule stated as behaviour: every construction states every value, or does not happen."""
    with pytest.raises(TypeError):
        ClaudeSettings(enabled=True)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        OpenAiSettings(cli_path=None)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        AgentSettings(claude=_CLAUDE)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        Settings(agents=_AGENTS)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        Project(  # type: ignore[call-arg]
            name=ProjectName("myapp"),
            repo=Path("/repo"),
            trees=TreesRoot(Path("/trees")),
            build="make",
        )


def test_a_missing_value_fails_before_any_validation_this_module_does() -> None:
    """`TypeError`, not `InputError`: nothing was supplied to refuse, so it is not a settings fault.

    Written with a value that `__post_init__` *would* refuse, so that a constructor which somehow
    defaulted the missing field would raise `InputError` here and be caught.
    """
    with pytest.raises(TypeError):
        Project(  # type: ignore[call-arg]
            name=ProjectName("myapp"),
            repo=Path("relative/repo"),
            trees=TreesRoot(Path("/trees")),
            build="   ",
        )


# --- Immutability -------------------------------------------------------------------------------


def test_every_settings_object_is_frozen() -> None:
    """Validated once on the way in is worth nothing if the value can be edited afterwards."""
    with pytest.raises(FrozenInstanceError):
        _CLAUDE.enabled = False  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        _OPENAI.cli_path = None  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        _AGENTS.claude = _CLAUDE  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        _SETTINGS.home = AglHome(Path("/elsewhere"))  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        _PROJECT.build_timeout = 0.0  # type: ignore[misc]


# --- What the constructors refuse ---------------------------------------------------------------


def test_a_relative_repo_is_refused() -> None:
    """It would resolve against whatever directory the process started in."""
    with pytest.raises(InputError, match="relative path"):
        Project(
            name=ProjectName("myapp"),
            repo=Path("dev/myapp"),
            trees=TreesRoot(Path("/trees")),
            build="make",
            build_timeout=60.0,
        )


@pytest.mark.parametrize("build", ["", " ", "\t\n  "])
def test_a_blank_build_command_is_refused(build: str) -> None:
    """A gate that runs nothing passes everything, which is worse than having no gate."""
    with pytest.raises(InputError, match="build"):
        Project(
            name=ProjectName("myapp"),
            repo=Path("/repo"),
            trees=TreesRoot(Path("/trees")),
            build=build,
            build_timeout=60.0,
        )


@pytest.mark.parametrize("timeout", [0.0, -1.0, -600.0, inf, -inf, nan])
def test_a_build_timeout_that_is_not_a_finite_positive_number_of_seconds_is_refused(
    timeout: float,
) -> None:
    """Zero or less kills every build at the start; infinity is a run that hangs unwatched."""
    with pytest.raises(InputError, match="build_timeout"):
        Project(
            name=ProjectName("myapp"),
            repo=Path("/repo"),
            trees=TreesRoot(Path("/trees")),
            build="make",
            build_timeout=timeout,
        )


def test_a_relative_cli_path_is_refused_by_each_section_under_its_own_name() -> None:
    """Both sections check it, and each says which section the operator should go and edit."""
    with pytest.raises(InputError, match="claude cli_path"):
        ClaudeSettings(enabled=True, cli_path=Path("bin/claude"))
    with pytest.raises(InputError, match="openai cli_path"):
        OpenAiSettings(enabled=True, cli_path=Path("../bin/harness"))


def test_an_absent_cli_path_is_a_value_and_not_a_refusal() -> None:
    """`None` means "resolve it from PATH", which is a decision the adapter carries out."""
    assert ClaudeSettings(enabled=True, cli_path=None).cli_path is None
    assert OpenAiSettings(enabled=False, cli_path=None).cli_path is None


# --- Where the refusals stop --------------------------------------------------------------------


def test_the_roots_enforce_their_own_absoluteness_and_it_is_not_re_checked_here() -> None:
    """A relative root never reaches `Project` or `Settings`: the wrapper refuses it first."""
    with pytest.raises(InputError, match="trees root"):
        TreesRoot(Path("relative/trees"))
    with pytest.raises(InputError, match="AGL_HOME"):
        AglHome(Path("relative/home"))


def test_nothing_is_asked_of_the_filesystem() -> None:
    """Pure functions of their arguments: existence is preflight's question, not this module's."""
    nowhere = Project(
        name=ProjectName("myapp"),
        repo=Path("/no/such/repository"),
        trees=TreesRoot(Path("/no/such/trees")),
        build="a-command-that-is-not-installed --please",
        build_timeout=0.5,
    )
    assert not nowhere.repo.exists()
    assert ClaudeSettings(enabled=True, cli_path=Path("/no/such/claude")).cli_path == Path(
        "/no/such/claude"
    )


def test_a_provider_can_be_configured_without_anything_claiming_it_is_available() -> None:
    """Configured is not available: there is no field here that could hold the second answer.

    `enabled` records what the operator asked for. Whether the harness is installed, on `PATH` and
    authenticated is `AgentRunner.check_ready(model)` at preflight, and a settings object that
    carried a cached answer to it would be wrong the first time a session expired.
    """
    section_fields = {field.name for field in fields(ClaudeSettings)} | {
        field.name for field in fields(OpenAiSettings)
    }
    assert section_fields == {"enabled", "cli_path"}
    assert ClaudeSettings(enabled=True, cli_path=Path("/no/such/claude")).enabled is True
