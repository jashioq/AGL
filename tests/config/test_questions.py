"""`config/questions.py`: what the operator is asked about each download, and what an answer does.

Two questions, both put after every download is fetched and inspected and before anything is
placed. **The collision** is asked where something already stands under the name a download goes
to, and it says only that it exists: whether anybody edited it since is no part of this question.
**The third-party dependencies** are asked where a download's `[project] dependencies` names
anything, and nowhere else - a prompt that fires on every download teaches `y` without reading. The
AGL bound in `[tool.agl] requires` is not one of them: nothing resolves it, and
`config/inspection.py` never hands it over.

**Answers are values, one per download.** A no skips its own download and nothing else, so every
later download is asked its own questions whatever an earlier one was answered. The first no settles
a download, which is why the collision is asked first: a download that is not placed installs
nothing, and asking about its dependencies would be noise.

**The operator here is a script.** `Confirm` is the whole of what `answered` knows about how a
question is put and read. The reader `agl` runs with is `cli/main.py`'s, and
`tests/cli/test_confirm.py` holds what it does with an answer that is not one and a closed stdin.
"""

from pathlib import Path
from typing import Final
import pytest
from agl.config.distribution import DISTRIBUTION, installed_version
from agl.config.inspection import PlaceableWorkflow, inspected
from agl.config.questions import (
    ApprovedWorkflow,
    Collision,
    DeclinedWorkflow,
    ThirdPartyDependencies,
    answered,
    needed,
)
from agl.config.registry import GROUP
from agl.ports.fetch import FetchedFile, FetchedWorkflow
from agl.ports.get_request import RepositoryAtRef, RequestedWorkflow
from agl.ports.home_layout import AglHome

_SHA: Final = "7fd1a60b01f91b314f59955a4e4d4e80d8edf11d"

# Never opened: a question names what stands there, and putting one reads nothing off disk.
_WORKFLOWS: Final = Path("/nowhere/workspace/workflows")

class _Interrupted(Exception):
    """What the operator's side raises part-way through a batch, as a Ctrl-D or a Ctrl-C would."""

class _Operator:
    """Answers each question with the next answer it was scripted with, and keeps every one."""

    def __init__(self, *answers: bool) -> None:
        self.asked: list[str] = []
        self._answers = list(answers)

    def __call__(self, question: str) -> bool:
        assert self._answers, f"asked {question!r} with no answer left to give"
        self.asked.append(question)
        return self._answers.pop(0)

def _requested(name: str) -> RequestedWorkflow:
    repository = RepositoryAtRef("jashioq", "myrepo", None)
    directory = f"workflows/mine/{name}"
    return RequestedWorkflow(repository, directory, f"{repository}/{directory}")

def _placeable(
    name: str, *, existing: str | None = None, dependencies: tuple[str, ...] = ()
) -> PlaceableWorkflow:
    """A download nothing refused, with `existing` standing in its place and `dependencies`."""
    standing = None if existing is None else _WORKFLOWS / existing
    return PlaceableWorkflow(_requested(name), _SHA, {}, dependencies, standing)

# --- which questions a download is asked ---------------------------------------------------------

def test_a_download_with_nothing_in_its_place_and_nothing_declared_is_asked_nothing() -> None:
    placeable = _placeable("triage")
    operator = _Operator()

    assert needed(placeable) == ()
    assert answered([placeable], operator) == (ApprovedWorkflow(placeable),)
    assert operator.asked == []

def test_a_download_where_something_already_stands_is_asked_the_collision_alone() -> None:
    placeable = _placeable("triage", existing="triage")

    assert needed(placeable) == (Collision(placeable.workflow, _WORKFLOWS / "triage"),)

def test_a_download_declaring_dependencies_is_asked_about_those_alone() -> None:
    placeable = _placeable("triage", dependencies=("rich",))

    assert needed(placeable) == (ThirdPartyDependencies(placeable.workflow, ("rich",)),)

def test_a_download_raising_both_is_asked_the_collision_first_and_its_dependencies_second() -> None:
    placeable = _placeable("triage", existing="triage", dependencies=("rich",))

    assert needed(placeable) == (
        Collision(placeable.workflow, _WORKFLOWS / "triage"),
        ThirdPartyDependencies(placeable.workflow, ("rich",)),
    )

def test_a_workflow_bound_only_to_an_agl_version_is_asked_no_question(tmp_path: Path) -> None:
    """The bound shares a file with the dependencies, and is inspected as it would be downloaded."""
    pyproject = (
        f'[project]\nname = "triage"\nversion = "0.1.0"\n\n'
        f'[project.entry-points."{GROUP}"]\ntriage = "triage:triage"\n\n'
        f'[tool.agl]\nrequires = "{DISTRIBUTION}>={installed_version()}"\n'
    ).encode()
    files = {"pyproject.toml": FetchedFile(pyproject), "__init__.py": FetchedFile(b"")}
    fetched = FetchedWorkflow(_requested("triage"), _SHA, files)
    (placeable,) = inspected([fetched], AglHome(tmp_path))
    assert isinstance(placeable, PlaceableWorkflow), placeable
    operator = _Operator()

    assert answered([placeable], operator) == (ApprovedWorkflow(placeable),)
    assert operator.asked == []

# --- what each question says --------------------------------------------------------------------

def test_the_collision_names_what_stands_there_as_it_is_spelled_on_disk() -> None:
    """`Triage` is where a download named `triage` goes, on a volume that folds case."""
    (question,) = needed(_placeable("triage", existing="Triage"))

    assert str(question) == (
        "/nowhere/workspace/workflows/Triage already exists. "
        "Override it with jashioq/myrepo/workflows/mine/triage?"
    )

def test_the_collision_says_only_that_it_exists_and_never_mentions_any_change() -> None:
    (question,) = needed(_placeable("triage", existing="triage"))
    said = str(question).casefold()

    for word in ("change", "edit", "modif", "local"):
        assert word not in said, said

def test_the_dependency_question_names_every_package_exactly_as_it_was_declared() -> None:
    """Quoted, so a comma inside a version specifier cannot read as one between two packages."""
    declared = (
        "httpx>=0.27",
        "pydantic>=2,<3",
        'rich; python_version < "3.13"',
        "probe @ https://example.invalid/probe-1.0.tar.gz",
    )
    (question,) = needed(_placeable("triage", dependencies=declared))

    assert str(question) == (
        "jashioq/myrepo/workflows/mine/triage depends on third-party packages uv will install "
        "into the workspace: 'httpx>=0.27', 'pydantic>=2,<3', 'rich; python_version < \"3.13\"', "
        "'probe @ https://example.invalid/probe-1.0.tar.gz'. Continue?"
    )

def test_a_control_character_in_a_dependency_is_shown_escaped_and_never_raw() -> None:
    """ESC and CR written raw would erase the line naming a URL and let an innocent one stand."""
    hostile = "probe @ https://example.invalid/probe.whl\x1b[2K\rrich"
    reordered = "rich ; python_version < '3.13\u202e'"
    (question,) = needed(_placeable("triage", dependencies=(hostile, reordered)))
    said = str(question)

    assert said.isprintable(), said
    assert repr(hostile) in said
    assert repr(reordered) in said

# --- what the answers do -------------------------------------------------------------------------

def test_a_no_to_the_collision_skips_the_download_and_its_dependency_question() -> None:
    placeable = _placeable("triage", existing="triage", dependencies=("rich",))
    collision = Collision(placeable.workflow, _WORKFLOWS / "triage")
    operator = _Operator(False)

    assert answered([placeable], operator) == (DeclinedWorkflow(placeable, collision),)
    assert operator.asked == [str(collision)]

def test_a_yes_to_the_collision_goes_on_to_ask_about_the_dependencies() -> None:
    placeable = _placeable("triage", existing="triage", dependencies=("rich",))
    collision, dependencies = needed(placeable)
    operator = _Operator(True, False)

    assert answered([placeable], operator) == (DeclinedWorkflow(placeable, dependencies),)
    assert operator.asked == [str(collision), str(dependencies)]

def test_a_download_answered_yes_to_every_question_it_was_put_is_approved() -> None:
    placeable = _placeable("triage", existing="triage", dependencies=("rich",))
    operator = _Operator(True, True)

    assert answered([placeable], operator) == (ApprovedWorkflow(placeable),)
    assert operator.asked == [str(question) for question in needed(placeable)]

def test_one_downloads_no_leaves_every_other_download_answered_on_its_own() -> None:
    first = _placeable("alpha", existing="alpha")
    second = _placeable("beta", existing="beta", dependencies=("rich",))
    third = _placeable("gamma", dependencies=("httpx",))
    (beta_collision, _) = needed(second)
    operator = _Operator(True, False, True)

    assert answered([first, second, third], operator) == (
        ApprovedWorkflow(first),
        DeclinedWorkflow(second, beta_collision),
        ApprovedWorkflow(third),
    )
    assert operator.asked == [str(needed(first)[0]), str(beta_collision), str(needed(third)[0])]

def test_every_question_is_asked_before_the_batch_hands_back_any_answer() -> None:
    """Interrupted at the last question, the batch hands back nothing: no earlier answer escapes.

    Nothing is placed until every answer is in, and a batch that handed answers back as they came
    would let its caller place the first download before the last question had been put.
    """
    placeables = [_placeable(name, existing=name) for name in ("alpha", "beta", "gamma")]
    asked: list[str] = []

    def interrupted_at_the_last(question: str) -> bool:
        asked.append(question)
        if len(asked) == len(placeables):
            raise _Interrupted(question)
        return True

    with pytest.raises(_Interrupted):
        answered(placeables, interrupted_at_the_last)
    assert asked == [str(needed(placeable)[0]) for placeable in placeables]
