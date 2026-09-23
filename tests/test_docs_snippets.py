"""The code the docs pages include, held to `DOCS_GUIDELINES.md`'s "Code on the page".

Every `.py` under `tests/docs/` imports nothing from AGL but `agl.sdk`. Every example workflow
there, copied into a fresh AGL home, loads through the real entry point the way
`agl workflows <name>` loads it. The types and lint gates cover `tests/` whole, `tests/docs/`
included.

These tests sit here rather than in `tests/docs/`. A test module there would import more of AGL than
`agl.sdk`, and pytest would put `tests/docs/` on `sys.path`, where `config/registry.py` finds each
example ahead of the workspace and refuses it as shadowed.
"""

import ast
import shutil
import sys
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final
import pytest
import agl.sdk
from agl.cli import main
from agl.ports.home_layout import AglHome, workflows_dir

REPO_ROOT: Final = Path(__file__).resolve().parent.parent
DOCS_CODE: Final = REPO_ROOT / "tests" / "docs"
PYPROJECT_FILE: Final = REPO_ROOT / "pyproject.toml"

# The one package the wheel ships: `agents-gl` names the distribution and is never imported.
AGL_PACKAGE: Final = "agl"

# The one module of AGL a page's code may import, and only the names it exports.
FRONT_DOOR: Final = "agl.sdk"

@dataclass(frozen=True)
class Foreign:
    """One import in a docs file that reaches AGL past `agl.sdk`, or leaves its own workflow.

    `imported` is the module as resolved, or `agl.sdk.<name>` for a name the front door does not
    export. A relative import that climbs out of its workflow keeps its written spelling.
    """

    line: int
    imported: str

def foreign_imports(source: str, *, package: str) -> list[Foreign]:
    """Every import in `source` a page's code may not make, in the order written.

    `package` is the file's own package below `tests/docs/`, `implement` for every module of that
    example and the empty string for a file directly inside, and is what a relative import is
    resolved against.
    """
    found: list[Foreign] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [
                Foreign(node.lineno, alias.name)
                for alias in node.names
                if _root(alias.name) == AGL_PACKAGE and alias.name != FRONT_DOOR
            ]
        elif isinstance(node, ast.ImportFrom):
            imported = _resolve(node, package)
            if imported is None:
                found.append(Foreign(node.lineno, "." * node.level + (node.module or "")))
            elif imported == FRONT_DOOR:
                found += [
                    Foreign(node.lineno, f"{FRONT_DOOR}.{alias.name}")
                    for alias in node.names
                    if alias.name != "*" and alias.name not in agl.sdk.__all__
                ]
            elif _root(imported) == AGL_PACKAGE:
                found.append(Foreign(node.lineno, imported))
    return sorted(found, key=lambda finding: (finding.line, finding.imported))

def _root(module: str) -> str:
    return module.partition(".")[0]

def _resolve(node: ast.ImportFrom, package: str) -> str | None:
    """The module `node` names, or `None` for a relative import that climbs out of `package`."""
    if not node.level:
        return node.module or ""
    parts = package.split(".") if package else []
    if node.level > len(parts):
        return None
    base = ".".join(parts[: len(parts) - node.level + 1])
    return f"{base}.{node.module}" if node.module else base

def _package_of(path: Path) -> str:
    return ".".join(path.relative_to(DOCS_CODE).parts[:-1])

def _shown(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))

def _examples() -> list[Path]:
    """Every directory under `tests/docs/` holding a project file, which is an example workflow."""
    return sorted(path.parent for path in DOCS_CODE.rglob("pyproject.toml"))

def _placed(example: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A fresh AGL home holding one copy of `example`, named by `AGL_HOME` as the CLI reads it."""
    home = AglHome(tmp_path / example.name / "home")
    shutil.copytree(
        example,
        workflows_dir(home) / example.name,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    monkeypatch.setenv("AGL_HOME", str(home.path))

def _agl(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    """One `agl` invocation through the real entry point: its exit status, stdout and stderr."""
    status = main.main(argv)
    captured = capsys.readouterr()
    return status, captured.out, captured.err

@pytest.fixture
def _forgotten_before_and_after() -> Iterator[None]:
    """Every example's package out of `sys.modules`, so each load imports the copy just placed.

    `tests/conftest.py` restores `sys.path` and not `sys.modules`, and a package already imported
    answers the next import from wherever it was first found.
    """
    names = {example.name for example in _examples()}

    def forget() -> None:
        for held in [name for name in sys.modules if _root(name) in names]:
            del sys.modules[held]

    forget()
    yield
    forget()

# --- The imports every docs file may make ---------------------------------------------------------

def test_every_python_file_under_tests_docs_imports_nothing_from_agl_but_agl_sdk() -> None:
    """`tests/docs/`, file by file, against "imports nothing from AGL except `agl.sdk`"."""
    sources = sorted(DOCS_CODE.rglob("*.py"))
    assert sources, f"{DOCS_CODE} holds no Python file, so this scan read nothing."
    problems = [
        f"{_shown(source)}:{finding.line} imports {finding.imported}. Code a page includes imports "
        f"from AGL only the names `{FRONT_DOOR}` exports, and a relative import stays inside its "
        f"own workflow."
        for source in sources
        for finding in foreign_imports(
            source.read_text(encoding="utf-8"), package=_package_of(source)
        )
    ]
    assert not problems, "\n\n".join(problems)

def test_the_wheel_ships_the_agl_package_alone_so_that_is_all_of_agl() -> None:
    """What the scan above counts as AGL, checked against what `pip install agents-gl` installs."""
    document = tomllib.loads(PYPROJECT_FILE.read_text(encoding="utf-8"))
    shipped = document["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    assert [Path(package).name for package in shipped] == [AGL_PACKAGE]

def test_the_scan_permits_agl_sdk_the_standard_library_and_the_workflows_own_modules() -> None:
    assert not foreign_imports(
        "from dataclasses import dataclass\n"
        "import agl.sdk\n"
        "from agl.sdk import Run, arg, workflow\n"
        "from agl.sdk import *\n"
        "from .roles import implementer\n"
        "from . import roles\n"
        "from implement.roles import implementer\n",
        package="implement",
    )

def test_the_scan_reports_an_agl_module_past_the_front_door_however_it_is_imported() -> None:
    findings = foreign_imports(
        "import agl\n"
        "from agl import sdk\n"
        "from agl.sdk.roles import Role\n"
        "import agl.testing as testing\n",
        package="implement",
    )
    assert findings == [
        Foreign(1, "agl"),
        Foreign(2, "agl"),
        Foreign(3, "agl.sdk.roles"),
        Foreign(4, "agl.testing"),
    ]

def test_the_scan_reports_a_name_agl_sdk_does_not_export_like_a_private_module() -> None:
    findings = foreign_imports("from agl.sdk import Run, _workflow\n", package="implement")
    assert findings == [Foreign(1, "agl.sdk._workflow")]

def test_the_scan_reports_a_relative_import_that_climbs_out_of_its_own_workflow() -> None:
    assert foreign_imports("from .. import other\n", package="implement") == [Foreign(1, "..")]
    assert foreign_imports("from .roles import x\n", package="") == [Foreign(1, ".roles")]

def test_the_scan_reads_imports_nested_in_functions_and_under_type_checking_alike() -> None:
    findings = foreign_imports(
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from agl.ports.agent import Claude\n"
        "def build() -> None:\n"
        "    import agl.config\n",
        package="implement",
    )
    assert findings == [Foreign(3, "agl.ports.agent"), Foreign(5, "agl.config")]

# --- Every example workflow loads the way `agl workflows <name>` loads it -------------------------

@pytest.mark.usefixtures("_forgotten_before_and_after")
def test_every_example_workflow_under_tests_docs_loads_and_prints_its_usage_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Each example lists its names in a fresh home, and each name exits 0 with its usage line."""
    examples = _examples()
    assert examples, f"{DOCS_CODE} holds no example workflow, so nothing was loaded."
    problems: list[str] = []
    for example in examples:
        _placed(example, tmp_path, monkeypatch)
        status, listed, said = _agl(capsys, "workflows")
        if status != 0 or said or not listed:
            problems.append(f"`agl workflows` over {_shown(example)} exited {status}: {said}")
            continue
        for name in listed.split():
            status, printed, said = _agl(capsys, "workflows", name)
            if status != 0 or said or not printed.startswith(f"usage: agl run {name} -n <label>"):
                problems.append(f"`agl workflows {name}` exited {status}: {said or printed}")
    assert not problems, "\n\n".join(problems)

@pytest.mark.usefixtures("_forgotten_before_and_after")
def test_the_implement_example_prints_a_usage_line_with_the_label_and_request_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _placed(DOCS_CODE / "implement", tmp_path, monkeypatch)

    status, printed, said = _agl(capsys, "workflows", "implement")

    assert (status, said) == (0, "")
    assert printed.splitlines()[0] == "usage: agl run implement -n <label> -r REQUEST"
