import argparse
import sys
from collections.abc import Callable
from agl import api
from agl.ports.errors import InternalError
from agl.ports.ids import ProjectName, RunLabel
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

# Never on stdout, for `cli/commands/workflows.py`'s reason: what a machine consumes goes there and
# this is a note to whoever is reading the terminal. Silent at zero, so the line's presence is the
# signal - every first run replays nothing, and a run that says so every time says nothing.
def _print_replays(label: RunLabel, replayed: api.Replayed) -> None:
    if not replayed.steps:
        return
    counted = "step" if replayed.steps == 1 else "steps"
    print(
        f"replayed {replayed.steps} {counted} from cache - `agl clear {label}` removes it.",
        file=sys.stderr,
    )
