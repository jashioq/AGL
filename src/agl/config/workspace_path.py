import sys
import sysconfig
from pathlib import Path
from typing import Final
from agl.ports.home_layout import AglHome, workflows_dir, workspace_site_packages

__all__ = ["extend"]

# What `sysconfig` substitutes for a scheme's `{base}` while composing the path `_interpreter`
# reads. Only the `lib/` subdirectory's name comes back out of it, and that name is the
# interpreter's rather than the base's - so every value answers alike and this one names no
# directory anything looks at.
_SUBSTITUTED_BASE: Final = "/venv"

def extend(home: AglHome) -> None:
    """Put the operator's workspace on this process's import path, appended and never inserted."""
    site = workspace_site_packages(home, _interpreter())
    # A workspace with no venv beside it is the ordinary shape for a workflow importing nothing
    # past `agl`, and one built by another interpreter leaves a `lib/` subdirectory that is simply
    # not there. Neither is a failure, and AGL creates neither.
    if site.is_dir():
        _append(str(site))
    # The container and not each workflow inside it: a workflow is then a package named after its
    # own directory, so two of them may both hold a `roles.py` without either shadowing the other.
    _append(str(workflows_dir(home)))

def _append(entry: str) -> None:
    # Appended, so whatever AGL's own environment provides keeps resolving from the earlier entry
    # it already resolved from - `agl` included, whatever a workspace venv holds under that name.
    # Membership is by the string, which is how `sys.path_importer_cache` is keyed as well: one
    # home twice adds nothing, and a second home lands beside the first rather than replacing it.
    if entry not in sys.path:
        sys.path.append(entry)

def _interpreter() -> str:
    # The `lib/` subdirectory a venv installs into, which `sys.version_info` gets wrong twice over:
    # a free-threaded build writes `python3.14t` and PyPy writes `pypy3.11`.
    composed = sysconfig.get_path(
        "purelib", vars={"base": _SUBSTITUTED_BASE, "platbase": _SUBSTITUTED_BASE}
    )
    return Path(composed).parent.name
