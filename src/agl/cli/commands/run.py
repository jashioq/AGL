import argparse
import asyncio
from collections.abc import Iterable, Sequence
from importlib.metadata import EntryPoint
from typing import Final
from agl import api
from agl.cli.commands import Registered, _print_replays, _said
from agl.ports.home_layout import AglHome
from agl.ports.ids import RunLabel
from agl.sdk.params import RefusingParser

__all__ = ["NAME", "declare", "execute"]

NAME: Final = "run"

_WORKFLOW: Final = "workflow"
_LABEL: Final = "label"
# `--from` would otherwise land on the attribute `from`, a keyword and unreachable except by
# `getattr`.
_BASE_REF: Final = "base_ref"

_LABEL_FLAGS: Final = ("-n", "--name")
_BASE_REF_FLAGS: Final = ("--from",)

_NOTHING_TO_REPORT: Final = 0

# `argparse` has no public spelling for what `add_subparsers` returns, and the alternative is
# `Any`, which is the one thing `mypy --strict` is here to keep out of the seam.
type _Commands = argparse._SubParsersAction[RefusingParser]

def declare(commands: _Commands) -> RefusingParser:
    parser = commands.add_parser(
        NAME,
        help="start a run",
        description=(
            "Start a run of a workflow. Flags this parser does not recognise belong to the "
            "workflow and are passed to it, so this help lists AGL's own and no workflow's: "
            "`agl workflows` lists what your workspace declares, and `agl workflows <workflow>` "
            "prints the flags one of them takes."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        _WORKFLOW,
        metavar="<workflow>",
        help="the workflow to run, named as its own pyproject.toml declares it, not as a directory",
    )
    parser.add_argument(
        *_LABEL_FLAGS,
        dest=_LABEL,
        metavar="<label>",
        required=True,
        help="this run's name: its record under AGL_HOME and the branch agl/<label>",
    )
    parser.add_argument(
        *_BASE_REF_FLAGS,
        dest=_BASE_REF,
        metavar="<ref>",
        help="the ref this run's work starts from (default: the repository's own default branch)",
    )
    return parser

def execute(
    registered: Registered,
    parsed: argparse.Namespace,
    argv: Sequence[str],
    *,
    home: AglHome,
    points: Iterable[EntryPoint] | None = None,
) -> int:
    name = _said(parsed, _WORKFLOW, command=NAME)
    label = RunLabel(_said(parsed, _LABEL, command=NAME))
    project, services = registered()
    replayed = asyncio.run(
        api.run(
            services,
            project,
            name,
            label,
            argv,
            base_ref=_perhaps(parsed, _BASE_REF),
            home=home,
            points=points,
        )
    )
    # Nought on every reachable path today, `api.run` refusing a label that has a record - so what
    # decides is the count and not the verb, and a `run` that could ever replay would say so with
    # no edit here. `tests/cli/test_resume_command.py` pins the silence from this side.
    _print_replays(label, replayed)
    print(f"run {str(label)!r} finished")
    return _NOTHING_TO_REPORT

def _perhaps(parsed: argparse.Namespace, dest: str) -> str | None:
    value = getattr(parsed, dest)
    return None if value is None else _said(parsed, dest, command=NAME)
