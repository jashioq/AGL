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
