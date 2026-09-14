import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Final
from agl.ports.errors import InputError
from agl.sdk._engine.services import Services

__all__ = ["DeclaredConfig", "narrowed", "required_setting"]

_PYPROJECT_FILE: Final = "pyproject.toml"

# Refuses with an `InputError` and never a `KeyError`: `Mapping.get` and `Mapping.__contains__` are
# written over `__getitem__` and catch `KeyError` alone, so a `KeyError` here would reach a workflow
# as `None` or `False`, and this one passes through both of them.
class DeclaredConfig(Mapping[str, str]):
    def __init__(
        self,
        config: Mapping[str, str],
        workflow: str,
        declared: Sequence[str],
        directory: Path | None,
    ) -> None:
        self._values = {key: config[key] for key in declared}
        self._workflow = workflow
        self._directory = directory

    def __getitem__(self, key: object) -> str:
        if not isinstance(key, str) or key not in self._values:
            raise InputError(_undeclared(key, self._workflow, tuple(self._values), self._directory))
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

def narrowed(
    services: Services, workflow: str, declared: Sequence[str], directory: Path | None
) -> Services:
    return replace(
        services, config=DeclaredConfig(services.config, workflow, declared, directory)
    )

def required_setting(config: Mapping[str, str], key: str, reader: str, consequence: str) -> str:
    if isinstance(config, DeclaredConfig):
        workflow, declared, directory = config._workflow, tuple(config._values), config._directory
    else:
        # A bundle no walk narrowed - `testing.a_run`'s, or a `Services` built by hand - so its keys
        # are its declaration, as `api._configured` makes them for entry points handed over.
        workflow, declared, directory = None, tuple(config), None
    if key not in declared:
        raise InputError(_unread(key, reader, consequence, workflow, declared, directory))
    return config[key]

def _undeclared(
    key: object, workflow: str, declared: Sequence[str], directory: Path | None
) -> str:
    return (
        f"the workflow {workflow!r} reads the project setting {key!r}, and its `config` line "
        f"{_holds(declared)}. A project file is checked for exactly the keys a workflow declares, "
        f"before anything is spent, so a key read from outside that list is one no project was "
        f"ever asked for - and answering `None` would put that hole into whatever was being built "
        f"from it. Nothing was read. {_declaration(key, declared, directory)}"
    )

def _unread(
    key: str,
    reader: str,
    consequence: str,
    workflow: str | None,
    declared: Sequence[str],
    directory: Path | None,
) -> str:
    named = "the workflow" if workflow is None else f"the workflow {workflow!r}"
    return (
        f"{named} calls {reader}, which reads the project setting {key!r}, and its `config` line "
        f"{_holds(declared)}. {consequence}. {_declaration(key, declared, directory)}"
    )

def _holds(declared: Sequence[str]) -> str:
    return f"declares {', '.join(declared)} and nothing else" if declared else "declares no key"

def _declaration(key: object, declared: Sequence[str], directory: Path | None) -> str:
    # `json.dumps` writes only escapes a TOML basic string also reads, so each name pastes as one.
    line = ", ".join(json.dumps(str(name)) for name in (*declared, key))
    return f"Declare it as `config = [{line}]` in the [tool.agl] table of {_declared_in(directory)}"

def _declared_in(directory: Path | None) -> str:
    if directory is not None:
        return (
            f"{directory / _PYPROJECT_FILE}, and every project this workflow runs against then "
            f"has to set it"
        )
    return (
        f"the workflow's own {_PYPROJECT_FILE}. This run read no {_PYPROJECT_FILE} - it was handed "
        f"its entry points rather than a workspace, or its bundle was built by hand - so what it "
        f"declares is the config that bundle was built with, which "
        f"`agl.testing.harness(config=...)` takes, and where the key needs a value too"
    )
