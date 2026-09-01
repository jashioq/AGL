import argparse
from collections.abc import Callable
from agl.ports.errors import InternalError
from agl.ports.ids import ProjectName
from agl.sdk._engine.services import Services

__all__ = ["Registered"]

type Registered = Callable[[], tuple[ProjectName, Services]]

def _said(parsed: argparse.Namespace, dest: str, *, command: str) -> str:
    value = getattr(parsed, dest)
    if isinstance(value, str):
        return value
    raise InternalError(
        f"the `{command}` parser produced {value!r} for {dest!r}, and every argument this module "
        f"declares is a string it took off the command line. That is AGL's own bug: the parser and "
        f"the reader are in one file and they disagree"
    )
