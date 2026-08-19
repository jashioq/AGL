"""The corpus the two layout suites share, and the three helpers both of them need.

Same technique as `test_ids.py`, for the same reasons: built here and deterministically rather
than drawn by `hypothesis`, because taking a new dependency is a project-level decision and not
this test's to make, and because a failure that reproduces on the next run costs nobody a seed.
Shared between the two suites rather than copied into each, because the property they check is
one property - *no value `ids.py` accepts can produce a path outside the root it was joined
onto* - and two corpora are two coverages, of which only one ever gets read.

The invisible characters are written as escapes rather than as themselves: a case that reads
`assert "a b" == "a b"` in a diff is worse than no case at all.
"""

import ast
import random
import shutil
import subprocess
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import ModuleType
from typing import Final

from agl.ports.errors import InputError
from agl.ports.ids import Namespace

_SEED: Final = 20260819

# Non-ASCII that is legal in a git ref and on disk and a trap anyway, plus non-ASCII that has to
# stay legal: NEL, no-break space, soft hyphen, zero width space, right-to-left override, line
# separator, ideographic space, byte order mark, a lone surrogate, a private-use codepoint - then
# e-acute composed and decomposed, the fullwidth solidus that looks like a separator, a CJK
# ideograph, a banana, and a letter whose casefold is not its lowercase.
_NON_ASCII: Final = [
    "\x85", "\xa0", "\xad", "\u200b", "\u202e", "\u2028", "\u3000", "\ufeff", "\ud800", "\ue000",
    "\xe9", "e\u0301", "\uff0f", "\u65e5", "\U0001f34c", "\u0130",
]  # fmt: skip

# Everything the rules turn on, plus a few that must stay legal, placed in every position below.
_INTERESTING: Final = [*"/\\~^:?*[ .-@{}_+", "..", "//", "@{", ".lock", "\x00", "\t"]

# The names this layout spends on itself. None of them may become path depth or vanish.
_LAYOUT_WORDS: Final = [
    "projects", "runs", "steps", "worktrees", "run.json", "agl", "main", "HEAD",
    "_base", "_BASE", "_Base", "_bases", "base",
    "CON", "con.toml", "T-01", "t-01", "banana", "x" * 255, "x" * 251, "x" * 250,
]  # fmt: skip


def _fuzz(count: int) -> list[str]:
    """Pseudo-random names from a fixed seed, so a failure reproduces without a seed to copy."""
    rng = random.Random(_SEED)
    alphabet = [*"abzAZ09._-", *"/\\~^:?*[ @{}", "\x00", "\t", "\xa0", "\xe9", "\U0001f34c"]
    return ["".join(rng.choices(alphabet, k=rng.randint(1, 12))) for _ in range(count)]


def _structured() -> list[str]:
    """The stated-coverage half: every ASCII codepoint, then every trap in every position."""
    values = [chr(code) for code in range(0x80)] + _NON_ASCII + _LAYOUT_WORDS
    for token in _INTERESTING + _NON_ASCII:
        values += [token, token * 2, f"{token}ab", f"ab{token}", f"a{token}b", f"ab{token}cd"]
    for name in ("CON", "NUL", "COM1", "LPT9"):
        values += [name, name.lower(), f"{name}.toml", f"{name}x", f"x{name}", f"{name}-1"]
    return values + ["COM0", "CONS", "CONSOLE", "NULL", "v1.0+build", "fix(auth)", "under_score"]


def _accepted(values: Sequence[str]) -> list[str]:
    """The subset `ids.py` takes. One validator serves all four types, so `Namespace` speaks."""
    kept: list[str] = []
    for value in values:
        try:
            kept.append(str(Namespace(value)))
        except InputError:
            pass
    return kept


STRUCTURED: Final = _structured()
CORPUS: Final = list(dict.fromkeys([*STRUCTURED, *_fuzz(2000)]))
ACCEPTED: Final = _accepted(CORPUS)

# The sample the git-ref properties spend a process on: every structurally interesting accepted
# value. Those properties turn on character coverage, not on volume.
REF_SAMPLE: Final = list(dict.fromkeys(_accepted(STRUCTURED)))

# What a pure layout module may import. Neither layout module is in it, which is how "neither
# imports the other" is checked rather than promised.
PURE_IMPORTS: Final = frozenset(
    {"dataclasses", "pathlib", "typing", "unicodedata", "agl.ports.errors", "agl.ports.ids"}
)

# Attribute names that mean the filesystem, the environment or the working directory. `resolve`
# is here with them: it reads symlinks, and a pure function of its arguments does not.
_IMPURE_ATTRIBUTES: Final = frozenset(
    """chdir cwd environ exists expanduser getcwd getenv glob home is_dir is_file iterdir lstat
    makedirs mkdir open read_bytes read_text rename replace resolve rglob rmdir rmtree samefile
    stat symlink_to touch unlink walk write_bytes write_text""".split()
)

# Bare names with the same meaning. Checked separately because `home` is a parameter name in
# `home_layout` and `Path.home()` is not: one is a name, the other an attribute.
_IMPURE_NAMES: Final = frozenset({"__import__", "compile", "eval", "exec", "input", "open"})


def _parsed(module: ModuleType) -> ast.Module:
    assert module.__file__ is not None
    return ast.parse(Path(module.__file__).read_text(encoding="utf-8"))


def impurities(module: ModuleType) -> set[str]:
    """Everything the module's *code* says that would touch the world. Parsed, so prose is safe."""
    found: set[str] = set()
    for node in ast.walk(_parsed(module)):
        if isinstance(node, ast.Attribute) and node.attr in _IMPURE_ATTRIBUTES:
            found.add(node.attr)
        elif isinstance(node, ast.Name) and node.id in _IMPURE_NAMES:
            found.add(node.id)
    return found


def imported_modules(module: ModuleType) -> set[str]:
    """What the module imports, by name, from its own source."""
    found: set[str] = set()
    for node in ast.walk(_parsed(module)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            found.add(node.module)
    return found


def git_rejects(refnames: Sequence[str]) -> list[str]:
    """The refnames real git turns down. Parallel because each one costs a process."""
    git = shutil.which("git")
    assert git is not None

    def rejected(name: str) -> bool:
        run = subprocess.run([git, "check-ref-format", name], capture_output=True)
        return run.returncode != 0

    with ThreadPoolExecutor(max_workers=8) as pool:
        verdicts = list(pool.map(rejected, refnames))
    return [name for name, bad in zip(refnames, verdicts, strict=True) if bad]
