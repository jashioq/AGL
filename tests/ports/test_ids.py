"""The rules these four names enforce, and the three properties nothing downstream re-checks.

Validation happens once, on the way in, so a hole here surfaces as a mangled path or a rejected
ref deep inside a later stage, with nothing in between to catch it. The properties in the middle
section are therefore checked over a corpus rather than over examples: every accepted value must
be free of path separators, must join into a path that stays inside its parent, and must satisfy
real `git check-ref-format`.

The corpus is built here, deterministically, rather than drawn by `hypothesis`: taking a new
dependency is a project-level decision and not this test's to make. Determinism is not purely a
consolation - a failure reproduces on the next run with no seed to copy out of the output, and
the coverage is stated rather than sampled. Four parts: every codepoint below 0x80 on its own;
the non-ASCII traps that ASCII alone would miss; every interesting character and sequence placed
at the start, the end, the middle and doubled; and a seeded pseudo-random fuzz over an alphabet
mixing safe characters with dangerous ones. What this gives up against a property-testing library
is shrinking, and the search for the case nobody thought of. If either becomes worth a dependency,
the properties below already take their corpus as an argument.

The invisible characters the corpus turns on are written as escapes rather than as themselves: a
case that reads `assert "a b" == "a b"` in a diff is worse than no case at all.
"""

import os
import random
import shutil
import subprocess
import unicodedata
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Final

import pytest

from agl.ports.errors import InputError
from agl.ports.ids import Namespace, ProjectName, RunLabel, StepName

_TYPES: Final = (RunLabel, Namespace, ProjectName, StepName)
_SEED: Final = 20260819

# Non-ASCII that is legal in a git ref and on disk and is a trap anyway, plus non-ASCII that has
# to stay legal. In order: NEL, no-break space, soft hyphen, Mongolian vowel separator, en quad,
# zero width space, zero width joiner, right-to-left override, line separator, paragraph
# separator, ideographic space, byte order mark, a lone surrogate (a `str` can hold one and a
# filesystem cannot), a private-use codepoint, a language tag - then e-acute composed, e-acute
# decomposed (one grapheme, two codepoints, a different string), the fullwidth solidus that looks
# like a separator and is not one, a CJK ideograph, a banana, and two letters whose casefold is
# not their lowercase.
_NON_ASCII: Final = [
    "\x85", "\xa0", "\xad", "\u180e", "\u2000", "\u200b", "\u200d", "\u202e",
    "\u2028", "\u2029", "\u3000", "\ufeff", "\ud800", "\ue000", "\U000e0001",
    "é", "é", "／", "日", "\U0001f34c", "Ω", "İ",
]  # fmt: skip

# Everything the rules turn on, plus a few that must stay legal, placed in every position below.
_INTERESTING: Final = [*"/\\~^:?*[ .-@{}_+", "..", "//", "@{", ".lock", ".LOCK", "\x00", "\t"]

_DEVICE_NAMES: Final = ["CON", "PRN", "AUX", "NUL", "COM1", "COM9", "LPT1", "LPT9"]


def _fuzz(count: int) -> list[str]:
    """Pseudo-random names from a fixed seed, so a failure reproduces without a seed to copy."""
    rng = random.Random(_SEED)
    alphabet = [*"abzAZ09._-", *"/\\~^:?*[ @{}", "\x00", "\t", "\xa0", "\xe9", "\U0001f34c"]
    return ["".join(rng.choices(alphabet, k=rng.randint(1, 12))) for _ in range(count)]


def _structured() -> list[str]:
    """The stated-coverage half of the corpus: exhaustive, then systematic."""
    values = [chr(code) for code in range(0x80)] + _NON_ASCII
    for token in _INTERESTING + _NON_ASCII:
        values += [token, token * 2, f"{token}ab", f"ab{token}", f"a{token}b", f"ab{token}cd"]
    for name in _DEVICE_NAMES:
        values += [name, name.lower(), name.capitalize(), f"{name}.toml", f"{name.lower()}.txt"]
        values += [f"{name}x", f"x{name}", f"{name}-1", f"{name}.a.b"]
    return values + ["COM0", "LPT0", "COM10", "CONS", "CONSOLE", "NULL", "banana", "T-01"]


_STRUCTURED: Final = _structured()
_FUZZ: Final = _fuzz(1500)
_CORPUS: Final = list(dict.fromkeys([*_STRUCTURED, *_FUZZ]))


def _accepted(values: Sequence[str]) -> list[str]:
    """The subset of `values` that `Namespace` takes. All four types agree - see below."""
    kept: list[str] = []
    for value in values:
        try:
            kept.append(str(Namespace(value)))
        except InputError:
            pass
    return kept


_ACCEPTED: Final = _accepted(_CORPUS)


# --- The rules, one case each ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "rule"),
    [
        ("", "empty"), (".", "traversal"), ("..", "traversal"),
        ("a/b", "one path segment"), ("a\\b", "one path segment"),
        ("a//b", "one path segment"),  # git's ban on consecutive slashes, via the ban on one
        ("a b", "SPACE"), (" ab", "SPACE"), ("ab ", "SPACE"), ("\tab", "U+0009"),
        ("a\x00b", "U+0000"), ("a\x1fb", "U+001F"), ("a\x7fb", "U+007F"),
        ("a\xa0b", "NO-BREAK SPACE"), ("a\u200bb", "ZERO WIDTH SPACE"), ("a\ud800b", "U+D800"),
        ("a~b", "reserve"), ("a^b", "reserve"), ("a:b", "reserve"),
        ("a?b", "reserve"), ("a*b", "reserve"), ("a[b", "reserve"),
        ("-ab", "flag"), ("a..b", "'..'"), (".ab", "starts with '.'"), ("ab.", "ends with '.'"),
        ("ab.lock", ".lock"), ("ab.LOCK", ".lock"), ("a@{1}", "reflog"), ("@", "HEAD"),
        ("CON", "device name"), ("con", "device name"), ("nul.toml", "device name"),
        ("Com9.a.b", "device name"), ("x" * 256, "255"),
    ],
)  # fmt: skip
def test_each_rule_rejects_with_a_message_naming_the_rule_and_the_value(
    value: str, rule: str
) -> None:
    """`agl run fix -n my/label` has to teach the reader something, not merely fail."""
    with pytest.raises(InputError) as caught:
        Namespace(value)
    message = str(caught.value)
    assert rule in message, f"message does not name the broken rule: {message}"
    assert repr(value) in message, f"message does not quote the offending value: {message}"
    assert "namespace" in message, f"message does not say which kind of name: {message}"


@pytest.mark.parametrize(
    "value",
    [
        "banana", "T-01", "t-01", "x", "42", "a.b", "v1.0+build", "fix(auth)", "under_score",
        "trailing-", "a@b", "CONS", "COM10", "NULL", "caf\xe9", "日本語", "x" * 255,
    ],
)  # fmt: skip
def test_a_name_that_breaks_no_rule_is_taken_by_all_four_types(value: str) -> None:
    """The rules are a denylist from git and the filesystem, not an invented character set."""
    for name_type in _TYPES:
        assert str(name_type(value)) == value


def test_each_type_raises_input_error_and_says_its_own_kind() -> None:
    """`InputError` because it is the user's typo and not our bug; the kind so they know which."""
    kinds = ("run label", "namespace", "project name", "step name")
    for name_type, kind in zip(_TYPES, kinds, strict=True):
        with pytest.raises(InputError, match=kind):
            name_type("bad name")


# --- The three properties, over the corpus ---------------------------------------------------


def test_the_corpus_is_big_enough_and_mixed_enough_to_mean_anything() -> None:
    """A corpus that accepted nothing, or rejected nothing, would pass every property below."""
    assert len(_CORPUS) > 1500, f"corpus collapsed to {len(_CORPUS)} values"
    assert 200 < len(_ACCEPTED) < len(_CORPUS) - 200, f"{len(_ACCEPTED)} of {len(_CORPUS)} accepted"


def test_property_no_accepted_name_contains_a_path_separator() -> None:
    """(a) The one that would let a name become path depth. `worktree()` alone creates that."""
    carriers = [value for value in _ACCEPTED if "/" in value or "\\" in value]
    assert not carriers, f"accepted names carrying a separator: {carriers[:10]}"


def test_property_an_accepted_name_joined_onto_a_root_stays_under_it(tmp_path: Path) -> None:
    """(b) Escaping the parent is what `..`, `/` and an empty segment are all worth catching."""
    root = tmp_path.resolve()
    for value in _ACCEPTED:
        joined = (root / value).resolve()
        assert joined.is_relative_to(root), f"{value!r} resolves out of its parent: {joined}"
        assert joined.parent == root, f"{value!r} is more than one segment deep: {joined}"
        assert joined != root, f"{value!r} resolves to the parent itself"


def _git_rejects(refnames: Sequence[str]) -> list[str]:
    """The refnames real git turns down. Parallel because each one costs a process."""
    git = shutil.which("git")
    assert git is not None
    assert not any(name.startswith("-") for name in refnames), (
        "check-ref-format has no `--`, so it cannot be asked about a name beginning with '-' - "
        "which is one of the reasons the validator rejects those outright"
    )

    def rejected(name: str) -> bool:
        run = subprocess.run(
            [git, "check-ref-format", "--allow-onelevel", name], capture_output=True
        )
        return run.returncode != 0

    with ThreadPoolExecutor(max_workers=8) as pool:
        verdicts = list(pool.map(rejected, refnames))
    return [name for name, bad in zip(refnames, verdicts, strict=True) if bad]


@pytest.mark.skipif(
    shutil.which("git") is None,
    reason="git is not on PATH, so the git-ref-format property went UNVERIFIED",
)
def test_property_every_accepted_name_satisfies_real_git_check_ref_format() -> None:
    """(c) Asked of git itself, in the composed forms AGL actually creates.

    The sample is every structurally interesting accepted value plus a slice of the fuzz: each
    call costs a process, and this property turns on character coverage rather than on volume.
    """
    sample = _accepted(_STRUCTURED) + _accepted(_FUZZ)[:100]
    refnames = [
        *sample,  # the bare component, which is what --allow-onelevel is for
        *(f"refs/heads/agl/{value}" for value in sample),  # the branch a run label becomes
        *(f"refs/heads/agl/{value}/{value}" for value in sample),  # ... a namespace under it
    ]
    rejected = _git_rejects(refnames)
    assert not rejected, f"git rejects {len(rejected)} of {len(refnames)}: {rejected[:10]}"


def test_git_would_have_said_so_if_the_property_above_were_vacuous() -> None:
    """The control: the same helper, on names git must refuse. A stub would pass (c) silently."""
    if shutil.which("git") is None:
        pytest.skip("git is not on PATH, so the git-ref-format property went UNVERIFIED")
    known_bad = ["a b", "a~b", "a..b", ".a", "a.lock", "@", "a@{1}", "a\\b"]
    assert sorted(_git_rejects(known_bad)) == sorted(known_bad)


# --- Opacity, and the shape of the types -----------------------------------------------------


def test_the_four_types_accept_exactly_the_same_language() -> None:
    """One validator, and no type with a vocabulary of its own. Checked, not claimed in prose."""
    disagreed: list[str] = []
    for value in _CORPUS:
        verdicts = set()
        for name_type in _TYPES:
            try:
                name_type(value)
            except InputError:
                verdicts.add(False)
            else:
                verdicts.add(True)
        if len(verdicts) != 1:
            disagreed.append(value)
    assert not disagreed, f"the types disagree about: {disagreed[:10]}"


def test_renaming_t01_to_banana_changes_nothing() -> None:
    """The plan's own test of opacity: no ticket, run or project vocabulary is baked in."""
    ticket, nonsense = Namespace("T-01"), Namespace("banana")
    assert (str(ticket), ticket.collision_key) == ("T-01", "t-01")
    assert (str(nonsense), nonsense.collision_key) == ("banana", "banana")
    for word in ("ticket", "run", "project", "step", "workflow", "agl", "main", "HEAD"):
        assert str(Namespace(word)) == word


def test_a_name_is_not_a_string_and_not_a_path() -> None:
    """A `str` subclass would pass silently where a `str` is expected; that is the whole hole."""
    label = RunLabel("T-01")
    assert not isinstance(label, str)
    assert str(label) == f"{label}" == "T-01"
    assert repr(label) == "RunLabel(value='T-01')"
    assert not hasattr(label, "__fspath__"), "these are names, not paths"
    with pytest.raises(TypeError):
        os.fspath(label)  # type: ignore[call-overload]


def test_a_validated_name_of_one_kind_is_not_a_name_of_another() -> None:
    """Distinct at runtime - and the ignores below are the same guarantee, stated statically.

    `mypy --strict` calls each of these comparisons non-overlapping because it already knows a
    `RunLabel` can never equal a `Namespace`. That is the wanted answer, so the ignores stay;
    the asserts pin it at runtime, where a `dict` keyed on one type would otherwise be
    reachable with the other.
    """
    assert RunLabel("x") != Namespace("x")  # type: ignore[comparison-overlap]
    assert Namespace("x") != ProjectName("x")  # type: ignore[comparison-overlap]
    assert ProjectName("x") != StepName("x")  # type: ignore[comparison-overlap]
    assert RunLabel("x") == RunLabel("x")
    assert len({RunLabel("x"), Namespace("x"), ProjectName("x"), StepName("x")}) == 4
    assert Namespace("x") not in {RunLabel("x"): 1}  # type: ignore[comparison-overlap]


def test_a_name_is_frozen_and_slotted_so_it_cannot_be_edited_past_its_validation() -> None:
    label = RunLabel("T-01")
    with pytest.raises(FrozenInstanceError):
        label.value = "../escape"  # type: ignore[misc]
    assert not hasattr(label, "__dict__")


def test_collision_key_folds_the_two_ways_a_filesystem_merges_distinct_names() -> None:
    """Case on a case-insensitive volume, NFC/NFD on a normalising one. A key, not equality."""
    assert RunLabel("T-01") != RunLabel("t-01")
    assert RunLabel("T-01").collision_key == RunLabel("t-01").collision_key
    composed, decomposed = "caf\xe9", unicodedata.normalize("NFD", "caf\xe9")
    assert composed != decomposed
    assert Namespace(composed).collision_key == Namespace(decomposed).collision_key
    assert Namespace("T-01").collision_key != Namespace("T-02").collision_key
