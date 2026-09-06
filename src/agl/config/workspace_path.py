import sys
import sysconfig
from contextlib import suppress
from pathlib import Path
from typing import Final
from agl.ports.home_layout import (
    AglHome,
    workflows_dir,
    workspace_editor_pth,
    workspace_site_packages,
)

__all__ = ["extend", "venv_exists", "write_editor_pth"]

# The directory holding the `agl` package this process imported, which is `src/` in a checkout and
# an environment's own site-packages everywhere else. Composed from this module's location because
# `agl.__file__` is typed `str | None` and this one is not.
_AGL_PARENT: Final = Path(__file__).parent.parent.parent

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

# Asked before an installer is started and never after it has finished: `uv sync` builds the venv
# before it resolves, so a sync that failed on the first ever attempt leaves one standing, and an
# answer read afterwards would report an environment nothing has installed into. `api.py` is the
# caller, and the rule it decides with this is written there.
def venv_exists(home: AglHome) -> bool:
    """Whether this interpreter has a workspace venv to import from - `extend`'s own question."""
    return workspace_site_packages(home, _interpreter()).is_dir()

# For the editor an operator writes workflows in, and for nothing that runs. `site` reads a `.pth`
# while it builds `sys.path` for the interpreter that owns the venv, and no run of AGL is that
# interpreter: `extend` above reaches the same site-packages through `sys.path.append`, which
# processes no file at all. So `import agl` resolves where it always did, whatever is written here.
def write_editor_pth(home: AglHome) -> None:
    """Put the running AGL within reach of the workspace venv, so an editor resolves `agl.sdk`."""
    interpreter = _interpreter()
    # `extend`'s own two absences, answered the same way: a workspace whose sync installed nothing
    # has no venv, and one built by another interpreter leaves a `lib/` subdirectory that is not
    # this one. An unwritable file joins them, this being an editor's convenience rather than any
    # part of a run - a sync that installed what was asked for is not a sync that failed.
    if not workspace_site_packages(home, interpreter).is_dir():
        return
    # Rewritten rather than left alone, because the line is an absolute path and an AGL that moved
    # leaves a stale one behind. UTF-8 because that is what `site` decodes a `.pth` with first.
    written = f"{_AGL_PARENT}\n".encode()
    path = workspace_editor_pth(home, interpreter)
    # Silent rather than reported, and what decides that is where a report would have to travel:
    # back through `api._sync_workspace` and its `SyncOutcome`, which is the installer's word about
    # an install and no place for an editor's convenience. What the silence costs is a sync that
    # says it finished over a venv holding no `agl.pth` - visible in the editor and nowhere else.
    with suppress(OSError):
        if not path.is_file() or path.read_bytes() != written:
            path.write_bytes(written)

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
