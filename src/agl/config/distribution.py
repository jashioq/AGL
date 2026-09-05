from importlib.metadata import PackageNotFoundError, version
from typing import Final

__all__ = ["DISTRIBUTION", "UNINSTALLED", "installed_version"]

# `importlib.metadata` keys on the *distribution* name, not on the import package this module sits
# in: an import statement says `agl`, PyPI holds `agents-gl`, and `version("agl")` raises
# `PackageNotFoundError` on a machine where AGL is installed correctly. Pinned against
# `pyproject.toml`'s `[project] name` by `tests/config/test_distribution.py`.
DISTRIBUTION: Final = "agents-gl"

UNINSTALLED: Final = f"unknown ({DISTRIBUTION} is not installed)"

def installed_version() -> str:
    # A checkout that was never installed carries no `.dist-info` at all, which is the whole of
    # when this arm is reached: an editable install writes one and never comes here.
    try:
        return version(DISTRIBUTION)
    except PackageNotFoundError:
        return UNINSTALLED
