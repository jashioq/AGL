from importlib.metadata import PackageNotFoundError, version
from typing import Final
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

__all__ = [
    "DISTRIBUTION",
    "UNINSTALLED",
    "installed_version",
    "requirement",
    "unsatisfied_bound",
]

# `importlib.metadata` keys on the *distribution* name, not on the import package this module sits
# in: an import statement says `agl`, PyPI holds `agents-gl`, and `version("agl")` raises
# `PackageNotFoundError` on a machine where AGL is installed correctly. Pinned against
# `pyproject.toml`'s `[project] name` by `tests/config/test_distribution.py`.
DISTRIBUTION: Final = "agents-gl"

UNINSTALLED: Final = f"unknown ({DISTRIBUTION} is not installed)"

# PEP 503 says `agents_gl`, `Agents-GL` and `agents-gl` are one project, and the normalisation that
# says so folds runs of `-`, `_` and `.` together as well as case - which `str.lower()` does not.
_CANONICAL: Final = canonicalize_name(DISTRIBUTION)

# A floor and never a ceiling. A workflow is written against the AGL that scaffolded it and keeps
# working as AGL grows; what breaks it is an *older* AGL missing a name it imports, so the bound
# `agl new` writes says how far back the workflow may be carried and nothing about how far forward.
_AT_LEAST: Final = ">="

def installed_version() -> str:
    # A checkout that was never installed carries no `.dist-info` at all, which is the whole of
    # when this arm is reached: an editable install writes one and never comes here.
    try:
        return version(DISTRIBUTION)
    except PackageNotFoundError:
        return UNINSTALLED

def requirement() -> str | None:
    """The bound `agl new` writes into a workflow, `None` where there is no version to bound by."""
    running = _running_version()
    return None if running is None else f"{DISTRIBUTION}{_AT_LEAST}{running}"

def unsatisfied_bound(declared: object) -> str | None:
    """The specifier on AGL that the running AGL fails, out of a `[project] dependencies` value."""
    running = _running_version()
    # Silence, not a refusal, in both directions. AGL running from a source tree has no version to
    # compare and would otherwise refuse every workflow at once, this suite included; and a
    # `dependencies` that is absent, empty or not a list is a workflow making no claim about AGL,
    # which is every workflow written before this bound existed.
    if running is None or not isinstance(declared, list):
        return None
    for entry in declared:
        bound = _bound(entry)
        if bound is not None and not bound.specifier.contains(running):
            return str(bound.specifier)
    return None

def _running_version() -> Version | None:
    # `UNINSTALLED` is the string that lands here, and PEP 440 admits neither its leading letter nor
    # its spaces - so the sentence `installed_version` answers a bare checkout with is refused by
    # the parser rather than by a comparison against a constant.
    try:
        return Version(installed_version())
    except InvalidVersion:
        return None

def _bound(entry: object) -> Requirement | None:
    if not isinstance(entry, str):
        return None
    # An entry this cannot read is the installer's to complain about and not AGL's: uv resolves
    # every line of that list and AGL reads one of them, so a typo in somebody's `httpx` line is
    # not a reason to refuse the workflow.
    try:
        parsed = Requirement(entry)
    except InvalidRequirement:
        return None
    # A marker goes the same way. Deciding whether `; sys_platform == "win32"` applies to this
    # machine is the resolver's, and guessing it wrong refuses a workflow that would have run.
    if parsed.marker is not None:
        return None
    return parsed if canonicalize_name(parsed.name) == _CANONICAL else None
