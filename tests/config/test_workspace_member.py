"""`config/workspace_member.py`: what uv makes of a workflow's pyproject.toml as a workspace member.

Every directory under `workflows/` is a member of one uv workspace, and **uv refuses to sync any of
it over one member it cannot read** - so a download placed with a bad project file costs every
other workflow in the workspace its install, not only itself. Each refusal below was seen of uv 0.11
before it was written, `uv sync --offline` over a scratch workspace holding one member of the shape:
no name or one PEP 508 does not admit, no version or one PEP 440 does not read, a `requires-python`
uv cannot read or the running interpreter falls outside, and dependencies that are not a list of
requirement strings. An unreadable requirement is the subtle one: uv does not refuse it but falls
back to *building* the member to learn what it depends on, installing a build backend and running
it - and a field left `dynamic` sends uv down the same road.

Past what breaks the sync is what the sync would install that `[project] dependencies` does not
name, which matters because that list is the one the operator is asked about. Seen of uv 0.11:
every extra and every dependency group is resolved, a git requirement in either is cloned, the `dev`
group is installed, and `[tool.uv]` repoints a named dependency to a source of its own choosing,
installs a list of its own, or holds a nested workspace uv refuses outright.

**Two refusals go further than uv does, and on AGL's own ground.** A `dynamic` field uv never
builds for - `readme` - is refused with the rest, because a workflow is never built and nothing
would ever fill it in; and `[tool.uv]` is refused as a table, inert keys included, because telling
the inert keys of a vendor's table from the rest is a list that goes stale with every uv release.
Empty tables and tables uv does not read are no obstacle, and neither is a version spelled the way
PEP 440 admits and nobody writes: uv took both `v1.0` and `1.0+local`.
"""

import sys
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Final
import pytest
from agl.config.workspace_member import (
    check_member,
    dependencies,
    dependency_names,
    distribution_name,
)
from agl.ports.errors import InputError

_PATH: Final = Path("jashioq/myrepo/workflows/triage/pyproject.toml")

_RUNNING: Final = ".".join(str(part) for part in sys.version_info[:3])

def _document(
    project: str = "", tables: str = "", *, head: str | None = None
) -> Mapping[str, object]:
    """A member's project file: a name and a version unless `head` says otherwise, then the rest."""
    written = 'name = "triage"\nversion = "0.1.0"' if head is None else head
    return tomllib.loads(f"[project]\n{written}\n{project}\n{tables}")

def _refusal(document: Mapping[str, object]) -> str:
    with pytest.raises(InputError) as refused:
        check_member(_PATH, document)
    said = str(refused.value)
    assert str(_PATH) in said
    return said

# --- a member uv syncs ----------------------------------------------------------------------------

@pytest.mark.parametrize(
    "document",
    [
        _document(),
        _document('dependencies = ["rich", "requests >= 2.31"]'),
        _document(f'requires-python = ">={sys.version_info.major}.{sys.version_info.minor}"'),
        _document("dynamic = []"),
        _document(head='name = "triage"\nversion = "v1.0"'),
        _document(head='name = "My.Work_flow"\nversion = "1.0+local"'),
        _document(tables="\n[tool.uv]\n\n[dependency-groups]\n\n[tool.ruff]\nline-length = 100\n"),
        _document(tables='\n[tool.agl]\nrequires = "agents-gl>=0.0.1"\n'),
    ],
)
def test_a_member_uv_syncs_as_it_stands_is_let_through_with_nothing_said(
    document: Mapping[str, object],
) -> None:
    check_member(_PATH, document)

# --- what uv refuses the whole workspace over ----------------------------------------------------

@pytest.mark.parametrize(
    "head",
    ['version = "0.1.0"', 'name = "my workflow"\nversion = "0.1.0"', 'name = 3\nversion = "1"'],
)
def test_a_name_uv_would_refuse_is_refused_before_it_breaks_the_whole_sync(head: str) -> None:
    assert "[project] name" in _refusal(_document(head=head))

@pytest.mark.parametrize("head", ['name = "triage"', 'name = "triage"\nversion = "banana"'])
def test_a_version_missing_or_not_pep_440_is_refused_before_it_breaks_the_sync(head: str) -> None:
    assert "[project] version" in _refusal(_document(head=head))

def test_a_requires_python_the_running_interpreter_falls_outside_is_refused() -> None:
    said = _refusal(_document('requires-python = ">=99"'))

    assert ">=99" in said
    assert _RUNNING in said

@pytest.mark.parametrize("bound", ['requires-python = "banana"', "requires-python = 3"])
def test_a_requires_python_that_is_no_specifier_at_all_is_refused(bound: str) -> None:
    assert "requires-python" in _refusal(_document(bound))

@pytest.mark.parametrize(
    "declared", ['dependencies = "rich"', "dependencies = [3]", 'dependencies = ["rich >>>= 1"]']
)
def test_dependencies_that_are_not_a_list_of_pep_508_strings_are_refused(declared: str) -> None:
    assert "[project] dependencies" in _refusal(_document(declared))

# --- what uv would build, or install past the dependencies the operator is asked about ------------

@pytest.mark.parametrize(
    "dynamic",
    ['dynamic = ["version"]', 'dynamic = ["dependencies"]', 'dynamic = ["readme"]', "dynamic = 3"],
)
def test_a_field_left_dynamic_is_refused_since_only_a_build_would_fill_it_in(dynamic: str) -> None:
    assert "[project] dynamic" in _refusal(_document(dynamic))

@pytest.mark.parametrize(
    ("tables", "named"),
    [
        ('\n[project.optional-dependencies]\nx = ["rich"]\n', "[project.optional-dependencies]"),
        ('\n[dependency-groups]\ndev = ["rich"]\n', "[dependency-groups]"),
        ('\n[tool.uv.sources]\nrich = { git = "https://example.invalid/rich" }\n', "[tool.uv]"),
        ('\n[tool.uv]\ndev-dependencies = ["rich"]\n', "[tool.uv]"),
        ('\n[tool.uv.workspace]\nmembers = ["inner/*"]\n', "[tool.uv]"),
        ("\n[tool.uv]\npackage = true\n", "[tool.uv]"),
    ],
)
def test_a_table_taking_the_sync_past_the_dependencies_asked_about_is_refused(
    tables: str, named: str
) -> None:
    assert named in _refusal(_document(tables=tables))

# --- the names a member answers to, as uv compares them -------------------------------------------

def test_names_come_back_spelled_the_way_pep_503_says_uv_compares_them() -> None:
    document = _document(
        'dependencies = ["Rich_Text >= 1", "requests[socks]", "not a requirement !!"]',
        head='name = "Shared_Name"\nversion = "1"',
    )

    assert distribution_name(document) == "shared-name"
    assert dependency_names(document) == {"rich-text", "requests"}

def test_dependencies_come_back_verbatim_and_in_the_order_they_were_written() -> None:
    written = ["rich", "requests >= 2.31", "probe @ https://example.invalid/probe-1.0.tar.gz"]

    assert dependencies(_document(f"dependencies = {written!r}".replace("'", '"'))) == tuple(
        written
    )

@pytest.mark.parametrize("head", ['version = "1"', 'name = "trailing_"', 'name = 3'])
def test_a_name_uv_could_not_read_is_none_rather_than_a_refusal(head: str) -> None:
    """Asked of what already stands in the workspace, where a bad name is not a download's."""
    assert distribution_name(_document(head=head)) is None
