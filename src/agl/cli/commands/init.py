import argparse
from pathlib import Path
from typing import Final
from agl import api
from agl.api import Ask
from agl.config.schema import Settings
from agl.sdk.params import RefusingParser

__all__ = ["NAME", "declare", "execute"]

NAME: Final = "init"

_NOTHING_TO_REPORT: Final = 0

# `argparse` has no public spelling for what `add_subparsers` returns, and the alternative is
# `Any`, which is the one thing `mypy --strict` is here to keep out of the seam.
type _Commands = argparse._SubParsersAction[RefusingParser]

def declare(commands: _Commands) -> RefusingParser:
    return commands.add_parser(
        NAME,
        help="register this repository as a project",
        description=(
            "Register the repository you are in. AGL finds its git root, asks for the command "
            "that builds and tests it, picks a place beside it for the working checkouts, and "
            "writes the project's settings under AGL_HOME - never into the repository, so AGL "
            "never appears in `git status`. Run it once per repository."
        ),
        allow_abbrev=False,
    )

def execute(settings: Settings, cwd: Path, ask: Ask) -> int:
    written = api.init(settings, cwd, ask)
    print(f"init wrote {written}")
    return _NOTHING_TO_REPORT
