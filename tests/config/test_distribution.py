"""The reader of AGL's own version, and the name collision it exists to survive.

`importlib.metadata.version` takes a **distribution** name. AGL's distribution is `agents-gl`, the
package every import statement in this tree names is `agl`, and the console script is `agl` as well
- so the one spelling this call needs is the odd one out, and `version("agl")` is the repair
somebody makes while reading `config/distribution.py` inside a package called `agl`. Nothing else in
this build would notice: both spellings are `str`, so `mypy --strict` is content, `ruff` has no
opinion, and no import contract reads a string literal. It arrives as `PackageNotFoundError` on an
operator's machine, the first time anybody types `agl --version`.

This file is what notices instead, and it says the same thing twice on purpose. The pin compares
`DISTRIBUTION` against `[project] name` in the real `pyproject.toml` - the file that decides what
PyPI holds - so a wrong name fails in the edit that writes it and the failure names the file holding
the right one. The lookup below it performs the mistake rather than describing it, and derives the
import package name from the module under test rather than typing it, so a renamed package moves
the test with it instead of leaving a stale literal behind.

## The uninstalled answer is a path, not a defensive `except`

A checkout that was never installed has no `.dist-info` anywhere, and `agl --version` is what a
script calls to find out whether AGL is there at all - so the reader answers rather than raising.
What it answers with is a sentence no version parser would accept: it opens with a letter and holds
spaces, where PEP 440 admits neither. That is asserted rather than promised, because "cannot be
mistaken for a version" is the whole of why the string is not `0.0.0`.

The fallback is reached by pointing `DISTRIBUTION` at the import package name for the duration of
one test. Nothing is stubbed: the lookup is the real `importlib.metadata` one and the exception is
the real one it raises, and the only substitution is the name it is asked about - which is the same
wrong name the test below it proves has nothing behind it.
"""

import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Final
import pytest
from packaging.version import Version
from agl.config import distribution

# This repository's own `pyproject.toml`, which is where the distribution name is decided and the
# only artefact that could disagree with the constant under test.
_PYPROJECT: Final = Path(__file__).resolve().parents[2] / "pyproject.toml"

# The package an import statement names, read off the module under test rather than typed, so that
# renaming the tree renames this and the assertions keep meaning what they say.
_IMPORT_PACKAGE: Final = distribution.__name__.partition(".")[0]

def test_the_reader_answers_with_a_version_on_a_tree_that_is_installed() -> None:
    """`DISTRIBUTION` being the right name, on the one tree that is able to say so.

    This repository is worked on as an editable install, so the metadata is there and the reader
    has to find it. A name that is not the distribution's reads back as `UNINSTALLED` rather than
    raising, which is what would have made the mistake quiet; this is the assertion that makes it
    loud instead.
    """
    answered = distribution.installed_version()

    assert answered != distribution.UNINSTALLED, (
        f"`installed_version()` fell back to {answered!r} on an installed tree, so this "
        f"environment has no metadata under {distribution.DISTRIBUTION!r}. Either that name is "
        f"wrong - see the pin below, which compares it against {_PYPROJECT.name} - or this "
        f"editable install is gone, and `uv pip install -e . --no-deps` is what restores it."
    )

def test_the_reader_answers_uninstalled_rather_than_raising_when_no_metadata_is_there(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bare-checkout path, reached through the wrong name because it costs nothing to arrange.

    A source tree with no install has no `.dist-info` at all, and a name nothing installed answers
    to is indistinguishable from that tree as far as `importlib.metadata` is concerned: one
    `PackageNotFoundError`, raised by the real lookup. Only the name is substituted, so the arm
    under test is entered for the reason it exists rather than by a stub told to raise.
    """
    monkeypatch.setattr(distribution, "DISTRIBUTION", _IMPORT_PACKAGE)

    assert distribution.installed_version() == distribution.UNINSTALLED

def test_the_uninstalled_answer_is_a_sentence_and_not_a_version_number() -> None:
    """What `agl --version` prints where there is nothing to read has to be unmistakable.

    `0.0.0`, `unknown-0` or an empty string would all be taken for a version by something - a
    release script, a bug report, a person skimming. PEP 440 admits neither a leading letter nor a
    space anywhere, so a string with both is refused by every parser and reads as an explanation to
    everybody else. The installed version is asserted beside it because the contrast is the claim.
    """
    assert distribution.UNINSTALLED[0].isalpha()
    assert " " in distribution.UNINSTALLED
    assert distribution.installed_version()[0].isdigit()

def test_the_distribution_name_is_the_one_pyproject_declares_and_not_the_import_package() -> None:
    """The pin: one name, decided in `pyproject.toml`, read by `config/distribution.py`.

    Nothing else in the build compares these two. The wheel's metadata is written from `[project]
    name` and `importlib.metadata` is keyed by it, so this is the only artefact in the repository
    that can tell the right spelling from a plausible one.
    """
    parsed = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    project = parsed.get("project")
    assert isinstance(project, dict), (
        f"{_PYPROJECT} has no [project] table, so this test cannot tell what distribution this "
        f"repository builds. Check the path at the top of this file."
    )

    assert distribution.DISTRIBUTION == project.get("name"), (
        f"`config/distribution.py` looks {distribution.DISTRIBUTION!r} up and {_PYPROJECT.name} "
        f"declares {project.get('name')!r}. `importlib.metadata` keys on the distribution name, "
        f"which is what [project] name spells and is not the import package this tree is called: "
        f"a lookup of {_IMPORT_PACKAGE!r} raises `PackageNotFoundError` however many modules say "
        f"`import {_IMPORT_PACKAGE}`. Whichever of the two moved, {_PYPROJECT.name} decides."
    )

def test_looking_up_the_import_package_name_raises_because_it_is_no_distribution() -> None:
    """The mistake, performed. This is what `agl --version` would do with `agl` in the constant.

    The premise of everything above: `import agl` works and `agl` is nobody's distribution, so the
    two names are not interchangeable and no amount of reading `config/distribution.py` in context
    makes them so. If AGL is ever published under this name as well, this fails - which is the
    right moment to revisit the constant rather than a false alarm.
    """
    with pytest.raises(PackageNotFoundError):
        version(_IMPORT_PACKAGE)

# --- The bound a workflow declares on AGL, written by `agl new` and read before an import ------
#
# Two halves of one string and they are deliberately in one module: `requirement()` composes the
# line `config/toml_file.py` writes into a scaffold, and `unsatisfied_bound` reads that same line
# back out of `[tool.agl] requires` when `config/registry.py` walks the workspace. The round
# trip at the bottom is what says they are halves of one thing rather than two similar functions.
#
# **`packaging` and not a string comparison, which is the whole reason this repository grew a
# runtime dependency.** The check this replaces compared version *text*, and false refusals are
# what that produces: `"0.0.10" >= "0.0.2"` is False as strings and true as versions, and no
# ordering of text expresses a range at all. Both facts are asserted below rather than described.
#
# Nothing here reaches an index, and nothing here installs anything. The version being compared
# against is this interpreter's own metadata, which `installed_version` above already reads.

def _uninstalled(monkeypatch: pytest.MonkeyPatch) -> None:
    """The bare-checkout state, reached the way the test above reaches it: through a name nothing
    installed answers to, so the `PackageNotFoundError` is the real one."""
    monkeypatch.setattr(distribution, "DISTRIBUTION", _IMPORT_PACKAGE)

def test_the_bound_agl_new_writes_is_a_floor_naming_the_running_version() -> None:
    """`>=` and never `==`: a workflow keeps working as AGL grows and breaks on an older one.

    What a bound is for is the direction that breaks. A workflow's first line imports names out of
    `agl.sdk`, and an AGL *older* than the one it was written against is the AGL missing one of
    them; a newer one is the ordinary case and pinning it would refuse every upgrade. The version
    named is read back rather than restated, so this fails on the day the composition stops naming
    the running AGL at all.
    """
    written = distribution.requirement()

    assert written == f"{distribution.DISTRIBUTION}>={distribution.installed_version()}"

def test_an_agl_with_no_version_writes_no_requirement_into_a_scaffold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A source tree has no version, and `UNINSTALLED` is a sentence rather than one.

    Interpolating it would write `agents-gl>=unknown (agents-gl is not installed)` into somebody's
    project file - a requirement no resolver parses and no reader of this repository would have
    meant. Nothing is the honest answer: AGL cannot say which AGL scaffolded the workflow, so the
    scaffold makes no claim, and the reader below is silent for the same reason.
    """
    _uninstalled(monkeypatch)

    assert distribution.requirement() is None

def test_the_bound_a_scaffold_is_given_is_one_its_own_reader_accepts() -> None:
    """The round trip, and the one property that keeps `agl new` from scaffolding a refusal.

    `agl new` writes the bound and `config/registry.py` reads it back on the very next command, so
    a floor the reader does not accept is a workflow that cannot be run by the AGL that wrote it.
    The two are separate functions in this module and nothing but this asserts they agree.
    """
    written = distribution.requirement()
    assert written is not None, "this tree is installed, so there is a bound to round-trip"

    assert distribution.unsatisfied_bound(written) is None

def test_a_bound_the_running_agl_sits_below_comes_back_as_its_specifier() -> None:
    """What the refusal is built from: the specifier, not the whole requirement and not a bool.

    `config/registry.py` names the bound and the running version in one sentence, so what it needs
    back is the half the operator has to edit. A `>=` floor above the running version is the only
    shape that can be reached without knowing what this tree's version is.
    """
    running = Version(distribution.installed_version())
    above = f"{running.major + 1}.0.0"

    assert distribution.unsatisfied_bound(f"agents-gl>={above}") == f">={above}"

def test_a_bound_is_a_range_evaluated_as_versions_and_never_as_version_text() -> None:
    """The two halves of what a comparison of version text cannot do, on one running version.

    **Text is the wrong order.** `0.0.10` is above `0.0.2` as versions and below it as strings, so
    a floor of `0.0.2` admits it and a comparison of text refuses it - which is the shape every
    false refusal a text comparison makes has. The string comparison is written out beside it,
    because "the versions compare correctly" says nothing without the answer it is not giving.

    **And text expresses no range at all.** Four operators are put against the AGL that is running,
    two of which it satisfies and two of which it does not, and neither `==` nor `<` is something a
    floor-shaped check could have answered. The version is read back rather than written down, so
    this holds on any tree rather than on the one it was written against.
    """
    assert "0.0.10" < "0.0.2", "the textual comparison this check must not be"
    assert Version("0.0.10") > Version("0.0.2")

    running = distribution.installed_version()
    asked = {
        specifier: distribution.unsatisfied_bound(f"{distribution.DISTRIBUTION}{specifier}")
        for specifier in (f">={running}", f"=={running}", f">{running}", f"<{running}")
    }

    assert asked == {
        f">={running}": None,
        f"=={running}": None,
        f">{running}": f">{running}",
        f"<{running}": f"<{running}",
    }

@pytest.mark.parametrize(
    "spelled", ["agents-gl", "agents_gl", "Agents-GL", "AGENTS.GL", "agents--gl"]
)
def test_every_pep_503_spelling_of_the_distribution_names_the_same_project(spelled: str) -> None:
    """`packaging`'s own normalisation and not `.lower()`, which folds neither `_` nor a run.

    PEP 503 folds case *and* every run of `-`, `_` and `.` into one `-`, so all five spellings
    below are one project name and a workflow written by hand may use any of them. A refusal that
    matched on the exact string would pass over four of these and import the workflow anyway,
    which is the failure this whole check exists to prevent.
    """
    assert distribution.unsatisfied_bound(f"{spelled}>=99.0.0") == ">=99.0.0"

@pytest.mark.parametrize(
    "declared",
    [
        None,
        "",
        ["agents-gl>=99.0.0"],
        {"agents-gl": ">=99.0.0"},
        3,
        "httpx>=0.27",
        "agents-gl >>= 99",
        'agents-gl>=99.0.0; sys_platform == "some-machine-that-is-not-this-one"',
    ],
)
def test_a_requires_value_declaring_no_readable_agl_bound_refuses_no_workflow(
    declared: object,
) -> None:
    """Every shape that is not a bound on AGL, and all of them are silence rather than a refusal.

    Three different reasons, one answer. **Nothing was said**: absent, empty, or naming another
    distribution - which is every workflow written before the bound existed, and every one written
    by hand. **Nothing readable was said**: the bound exists to turn an `ImportError` on whichever
    name moved into a sentence, so a value that will not parse as a requirement carries no claim to
    convert, and refusing over its syntax would refuse a workflow that runs. **Nothing was said
    about this machine**: a marker names an environment, and a table only AGL reads has no resolver
    behind it to decide whether one applies - so AGL declines the question rather than guessing it.

    The wrong containers are in the list for the reader's sake. `requires` is a single string and
    TOML admits an array, a table and an integer in the same place; the array is the shape somebody
    carries over from `dependencies`, and it says nothing here rather than half-working.
    """
    assert distribution.unsatisfied_bound(declared) is None

def test_an_agl_that_is_not_installed_measures_no_bound_and_refuses_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The decision this whole check turns on: no version to compare is silence, not a refusal.

    A source tree carries no `.dist-info`, and this suite frequently runs in one - so a refusal
    here would refuse every workflow in the workspace at once and turn a missing install into a
    build that fails for the wrong reason. Silence also matches what the operator is owed: the
    bound converts an `ImportError` into a sentence, and where AGL cannot say which AGL it is there
    is nothing to convert. The bound below is one no released AGL will ever satisfy, so the
    silence is the uninstalled state answering and not the comparison passing.

    The bound is composed *before* the substitution, and that ordering is the assertion: what the
    substitution takes away is the version to compare against and nothing else, the name the reader
    matches on having been normalised at import. A bound spelled after it would name `agl`, match
    nothing, and pass without ever reaching the arm under test.
    """
    bound = f"{distribution.DISTRIBUTION}>=99.0.0"
    _uninstalled(monkeypatch)

    assert distribution.unsatisfied_bound(bound) is None
