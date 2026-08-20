"""The corpus the two layout suites share, and the three helpers both of them need.

Same technique as `test_ids.py`, for the same reasons: built here and deterministically rather
than drawn by `hypothesis`, because taking a new dependency is a project-level decision and not
this test's to make, and because a failure that reproduces on the next run costs nobody a seed.
Shared between the suites rather than copied into each, because the property they check is one
property - *no value `ids.py` accepts can produce a path outside the root it was joined onto* -
and two corpora are two coverages, of which only one ever gets read.

§3.3 made the character set an allowlist, which changed what a corpus is for here. Under a
blocklist the interesting values were the ones that got through; under an allowlist almost
nothing gets through, so the corpus has to be built from both ends. It carries the traps that
must be refused - shell metacharacters, non-ASCII, the invisibles, the reserved words in
several spellings - and, because a fuzz over a mixed alphabet now produces an accepted name
about one time in twenty, a second fuzz drawn only from characters the allowlist permits. A
corpus that accepted almost nothing would pass every containment property without checking one.

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
from agl.ports.ids import Namespace, ProjectName, RunLabel, StepName

_SEED: Final = 20260819

# Non-ASCII, every one of it now a *rejection* case: the allowlist is ASCII, so these earn their
# place by being the ones that used to be legal in a git ref and on disk. NEL, no-break space,
# soft hyphen, zero width space, right-to-left override, line separator, ideographic space, byte
# order mark, a lone surrogate, a private-use codepoint - then e-acute composed and decomposed,
# the fullwidth solidus that looks like a separator, a CJK ideograph, a banana, and a letter
# whose casefold is not its lowercase.
_NON_ASCII: Final = [
    "\x85", "\xa0", "\xad", "\u200b", "\u202e", "\u2028", "\u3000", "\ufeff", "\ud800", "\ue000",
    "\xe9", "e\u0301", "\uff0f", "\u65e5", "\U0001f34c", "\u0130",
]  # fmt: skip

# Everything the rules turn on, plus a few that must stay legal, placed in every position below.
# The second row is the shell: every one of these is legal in a ref and in a POSIX filename, and
# `decompose` invents the names that become namespaces, which is the whole argument for §3.3.
_INTERESTING: Final = [
    *"/\\~^:?*[ .-@{}_+", "..", "//", "@{", ".lock", "\x00", "\t",
    *"$`;|&><()!#'\"", "\n", "$(", "${", "&&", "||", ";;",
]  # fmt: skip

# The same characters as whole names, spelled the way they would actually arrive.
_SHELL_NAMES: Final = [
    "$(whoami)", "`whoami`", "${HOME}", "a;b", "a|b", "a&b", "a>b", "a<b", "a b; rm -rf .",
    "T-01 && echo", "a\nb", "a\rb", "$PATH", "--force", "-n", "..%2F..", "*", "?",
]

# The names this layout spends on itself. None of them may become path depth or vanish, and the
# first two are the words §3.3 reserves - `_base` for a namespace, `_work` for a label - which
# is why every spelling of each is here.
_LAYOUT_WORDS: Final = [
    "projects", "runs", "steps", "worktrees", "run.json", "agl", "main", "HEAD",
    "_base", "_BASE", "_Base", "_bAsE", "_bases", "base",
    "_work", "_WORK", "_Work", "_wOrK", "_works", "work",
    "CON", "con.toml", "T-01", "t-01", "banana", "x" * 255, "x" * 251, "x" * 250,
]  # fmt: skip

# Valid, and one character away from not being: the edges of "no leading or trailing `.` or `-`",
# of "non-empty", and of the two suffix rules. A rule with no case at its boundary is a rule
# nobody has checked.
_BOUNDARY: Final = [
    "a", "Z", "0", "_", "a-b.c", "_leading-underscore", "trailing_", "a.b.c", "a-1", "1-a",
    "-a", "a-", ".a", "a.", "-", ".", "..", "a..b", "a.lockb", "ab.lock", "ab.LOCK", "",
]  # fmt: skip


def _fuzz(count: int) -> list[str]:
    """Pseudo-random names from a fixed seed, so a failure reproduces without a seed to copy."""
    rng = random.Random(_SEED)
    alphabet = [*"abzAZ09._-", *"/\\~^:?*[ @{}$;|&`", "\x00", "\t", "\xa0", "\xe9", "\U0001f34c"]
    return ["".join(rng.choices(alphabet, k=rng.randint(1, 12))) for _ in range(count)]


def _permitted_fuzz(count: int) -> list[str]:
    """The other half: drawn only from characters the allowlist permits, so most are accepted.

    The mixed fuzz above answers "is anything dangerous getting through?". This one answers the
    question the containment properties actually ask - "of the names that do get through, does
    any of them compose into the wrong path?" - which needs accepted values in bulk, and which
    the mixed alphabet stopped supplying the day the character set became an allowlist. The
    positional rules still refuse a good few of these, which is the point of drawing `.` and `-`
    from the same hat as the letters.
    """
    rng = random.Random(_SEED + 1)
    return ["".join(rng.choices([*"abzAZ09._-"], k=rng.randint(1, 12))) for _ in range(count)]


def _structured() -> list[str]:
    """The stated-coverage half: every ASCII codepoint, then every trap in every position."""
    values = [chr(code) for code in range(0x80)] + _NON_ASCII + _LAYOUT_WORDS
    values += _SHELL_NAMES + _BOUNDARY
    for token in _INTERESTING + _NON_ASCII:
        values += [token, token * 2, f"{token}ab", f"ab{token}", f"a{token}b", f"ab{token}cd"]
    for name in ("CON", "NUL", "COM1", "LPT9"):
        values += [name, name.lower(), f"{name}.toml", f"{name}x", f"x{name}", f"{name}-1"]
    return values + ["COM0", "CONS", "CONSOLE", "NULL", "v1.0+build", "fix(auth)", "under_score"]


def _accepted(values: Sequence[str]) -> list[str]:
    """The subset every one of the four types takes.

    All four accept the same *language* from one validator, but §3.3 reserves one word per type
    - `_base` for a namespace, `_work` for a label - so a value that is a perfectly good
    `Namespace` need not be a `RunLabel`. Every consumer of this list builds several types from
    one value, so the list has to be the intersection rather than any one type's answer.
    """
    kept: list[str] = []
    for value in values:
        try:
            Namespace(value)
            RunLabel(value)
            ProjectName(value)
            StepName(value)
        except InputError:
            continue
        kept.append(value)
    return kept


STRUCTURED: Final = _structured()
CORPUS: Final = list(dict.fromkeys([*STRUCTURED, *_fuzz(2000), *_permitted_fuzz(600)]))
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
