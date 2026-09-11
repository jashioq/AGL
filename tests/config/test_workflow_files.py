"""`config/workflow_files.py`: one digest per file in a workflow's own directory.

The map is what a later comparison reads, and what it has to be able to say is *which* file moved -
`roles.py`, `prompts/review.md` - because a refusal ends a run somebody was in the middle of and a
count of changed files tells them nothing they can act on. So the shape asserted here is a mapping
from POSIX relative path to digest, and every case below is about a way that mapping can be wrong
while still looking right.

**The `__pycache__` case is the one that decides whether any of this works.** Importing a workflow
makes CPython write bytecode into the directory it just imported from, so a digest that counted it
would be changed by the very run that recorded it: the second reading never matches the first, and
a resume refuses every time.
`test_running_a_workflow_twice_changes_no_digest_because_bytecode_is_left_out` is the proof, and it
is deliberately not a directory made by hand - it drives `api.run` over a real
workflow package written under `tmp_path`, so the bytecode arrives the way it arrives in an
operator's workspace and the exclusion is measured against the thing it exists for.
`test_a_pycache_directory_planted_by_hand_reaches_neither_a_key_nor_a_digest` is the cheap version
beside it, and it is not a substitute: a directory somebody made proves the name is filtered, not
that the filter sits where the bytecode actually lands.

**Nothing here reaches the network or the operator's own home.** Every `AglHome` is built from
`tmp_path` rather than resolved, so no environment variable is read; the run goes over
`container.fakes()`, which has no credential to spend and starts no process; and the agent handed to
it fails the test if a turn is ever asked for.
"""

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Final
import pytest
from agl import api
from agl.config import container, registry
from agl.config.workflow_files import content_hash, digested, digests
from agl.ports.agent import AgentTask
from agl.ports.errors import InputError
from agl.ports.home_layout import AglHome, workflows_dir
from agl.ports.ids import ProjectName, RunLabel
from agl.ports.tree_layout import TreesRoot
from agl.sdk.testing import Reply

# `asyncio_mode = "strict"`, so the one async test below carries its own marker.

PROJECT: Final = ProjectName("myapp")

# The name the run below scaffolds, imports and runs, so it becomes a top-level module in this
# interpreter for the length of one test - distinctive for that reason, and removed again after.
IMPORTED: Final = "digested_workflow"

# A workflow shaped the way an operator writes one: a package whose `__init__.py` imports a sibling,
# so the import writes two `.pyc` files rather than one, and a prompt beside them so that a nested
# path is in the answer too.
_MODULE_DOCUMENT: Final = f"""from agl.sdk import Run, workflow
from .roles import NOTE

@workflow
async def {IMPORTED}(run: Run) -> None:
    assert NOTE
"""

_ROLES_DOCUMENT: Final = 'NOTE = "a sibling module, imported so that it compiles too"\n'

_PROMPT_DOCUMENT: Final = "# review\n\nread what changed and say what is wrong with it\n"

# The four files every case below starts from, sorted as `digests` is asserted to sort them.
_WRITTEN: Final = ("__init__.py", "prompts/review.md", "pyproject.toml", "roles.py")

# `Path.iterdir` as it was before a test replaced it, so the replacement can sort what the real one
# hands back rather than having to list a directory some other way.
_LISTING: Final = Path.iterdir

def _home(tmp_path: Path) -> AglHome:
    """An AGL_HOME nothing else can reach, built rather than resolved so no variable is read."""
    return AglHome(tmp_path / "home")

def _declaring(named: str) -> str:
    """The project file a workflow directory declares itself in, naming its own package."""
    return (
        f'[project]\nname = "{named}"\nversion = "0.1.0"\n\n'
        f'[project.entry-points."{registry.GROUP}"]\n{named} = "{named}:{named}"\n'
    )

def _workflow(home: AglHome, named: str) -> Path:
    """One importable workflow directory under the workspace: a package, a sibling and a prompt."""
    directory = workflows_dir(home) / named
    (directory / "prompts").mkdir(parents=True)
    (directory / "pyproject.toml").write_text(_declaring(named), encoding="utf-8")
    (directory / "__init__.py").write_text(_MODULE_DOCUMENT, encoding="utf-8")
    (directory / "roles.py").write_text(_ROLES_DOCUMENT, encoding="utf-8")
    (directory / "prompts" / "review.md").write_text(_PROMPT_DOCUMENT, encoding="utf-8")
    return directory

def _unwanted(task: AgentTask) -> Reply:
    """An agent that fails the test if a run reaches it: nothing here spends a turn."""
    raise AssertionError(f"a workflow being digested asked {task.model} for a turn")

def _reverse_sorted(directory: Path) -> Iterator[Path]:
    """A listing in the most adversarial order there is - the exact reverse of the answer."""
    return iter(sorted(_LISTING(directory), reverse=True))

@pytest.fixture
def _forgotten_afterwards() -> Iterator[None]:
    """The imported workflow, out of `sys.modules` again once the test that imported it is done.

    `tests/conftest.py` restores `sys.path` and not `sys.modules`, and the directory this name was
    imported from is deleted with `tmp_path` - so a later test scaffolding it would silently run
    this one's code out of a directory that is gone.
    """
    yield
    for held in [
        name for name in sys.modules if name == IMPORTED or name.startswith(f"{IMPORTED}.")
    ]:
        del sys.modules[held]

# --- the shape of the answer --------------------------------------------------------------------

def test_each_file_in_a_workflow_directory_gets_its_own_digest_under_a_posix_key(
    tmp_path: Path,
) -> None:
    """One entry per file, nested ones included, and the separator is `/` on every platform.

    The keys are asserted as a whole list rather than sampled, because what a later comparison
    names is exactly this set: a walk that quietly dropped `prompts/review.md` would still answer
    with three plausible entries and would report a changed prompt as no change at all.
    """
    directory = _workflow(_home(tmp_path), "triage")

    found = digests(directory)

    assert tuple(found) == _WRITTEN
    assert all(len(digest) == 64 for digest in found.values())

def test_the_keys_come_back_sorted_whatever_order_the_directory_lists_itself_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Directory order is the filesystem's business and differs between two machines.

    The listing is replaced with one handing back the exact reverse of the expected answer, so a
    mapping built in whatever order the entries arrived in fails here rather than passing on
    whichever order this machine's filesystem happened to choose.
    """
    directory = _workflow(_home(tmp_path), "triage")
    monkeypatch.setattr(Path, "iterdir", _reverse_sorted)

    assert tuple(digests(directory)) == _WRITTEN

def test_a_workflow_directory_that_is_not_there_refuses_rather_than_answering_with_nothing(
    tmp_path: Path,
) -> None:
    """An empty map is a legal answer for an empty directory, so it cannot also mean "no directory".

    Two workflows that are both missing would otherwise digest alike, and a comparison of the two
    would report them unchanged - which is the one answer a directory nobody can read must not give.
    """
    with pytest.raises(InputError) as refused:
        digests(workflows_dir(_home(tmp_path)) / "never-written")

    assert "never-written" in str(refused.value)

# --- the path is part of the digest and not only part of the key ---------------------------------

def test_two_files_holding_the_same_bytes_at_two_paths_never_share_one_digest(
    tmp_path: Path,
) -> None:
    """The direct measurement of the path being hashed in: identical content, two answers."""
    directory = _workflow(_home(tmp_path), "triage")
    (directory / "one.py").write_bytes(b"the same bytes\n")
    (directory / "prompts" / "one.py").write_bytes(b"the same bytes\n")

    found = digests(directory)

    assert found["one.py"] != found["prompts/one.py"]

def test_renaming_a_file_moves_its_key_and_changes_the_digest_that_answers_for_it(
    tmp_path: Path,
) -> None:
    """Both halves of what a rename does, because either alone would let one shape of rename pass.

    The key moving is what a comparison of two whole maps sees. The digest moving is what keeps a
    single entry honest on its own, so a reader holding one value out of the map cannot be handed
    a file's old answer under its new name.
    """
    directory = _workflow(_home(tmp_path), "triage")
    before = digests(directory)

    (directory / "roles.py").rename(directory / "helpers.py")
    after = digests(directory)

    assert "roles.py" in before and "roles.py" not in after
    assert after["helpers.py"] != before["roles.py"]

# --- the workflow's own pyproject.toml ------------------------------------------------------------

def test_the_workflows_own_pyproject_is_digested_so_a_moved_entry_point_invalidates_a_resume(
    tmp_path: Path,
) -> None:
    """The declaration decides which object a run calls, so one naming another is a change."""
    directory = _workflow(_home(tmp_path), "triage")
    before = digests(directory)

    (directory / "pyproject.toml").write_text(
        _declaring("triage").replace('"triage:triage"', '"triage.roles:triage"'), encoding="utf-8"
    )

    assert digests(directory)["pyproject.toml"] != before["pyproject.toml"]

def test_a_version_bump_in_that_same_pyproject_moves_the_digest_and_that_is_intended(
    tmp_path: Path,
) -> None:
    """The price of digesting the file rather than one table out of it, asserted as a decision.

    Nothing here can read a `[project] version` as cosmetic: what a digest sees is bytes, and the
    line that declares the entry point sits in the same file. Refusing a resume over a bump nobody
    meant as a change is the direction that costs a re-run rather than a replay against code the
    ledger was not written by, and it is written down here so that a later reader loosening it has
    to argue with a test rather than with a comment.
    """
    directory = _workflow(_home(tmp_path), "triage")
    before = digests(directory)

    (directory / "pyproject.toml").write_text(
        _declaring("triage").replace('version = "0.1.0"', 'version = "0.2.0"'), encoding="utf-8"
    )

    assert digests(directory)["pyproject.toml"] != before["pyproject.toml"]

# --- bytecode, which is the whole reason this is not a one-line walk ------------------------------

def test_a_pycache_directory_planted_by_hand_reaches_neither_a_key_nor_a_digest(
    tmp_path: Path,
) -> None:
    """The cheap half: the name is filtered, and a directory under it is not descended into."""
    directory = _workflow(_home(tmp_path), "triage")
    before = digests(directory)

    (directory / "__pycache__" / "nested").mkdir(parents=True)
    (directory / "__pycache__" / "roles.cpython-314.pyc").write_bytes(b"not source\n")
    (directory / "__pycache__" / "nested" / "deeper.pyc").write_bytes(b"nor this\n")

    assert digests(directory) == before

@pytest.mark.asyncio
@pytest.mark.usefixtures("_forgotten_afterwards")
async def test_running_a_workflow_twice_changes_no_digest_because_bytecode_is_left_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The proof, over a real run rather than over a directory this test made to look like one.

    The workflow is written into a workspace under `tmp_path` and reached the way an operator's is:
    `points=None`, so `config/registry.py` walks the workspace, `config/workspace_path.py` puts it
    on `sys.path`, and the package is imported from where it was written. That import is what
    writes the bytecode, and it is the reason a reading taken before the first run has to match the
    two taken after it - a digest that moved under its own run's feet is one no resume can use.

    **Two interpreter settings are pinned rather than assumed.** `sys.dont_write_bytecode` and
    `sys.pycache_prefix` are read at import time and either can be set on the machine this runs on,
    and with either against us no `__pycache__` would appear at all - leaving a test that passes
    while measuring nothing. The assertion that the directory is there afterwards is what says the
    exclusion was actually exercised.
    """
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    monkeypatch.setattr(sys, "pycache_prefix", None)
    home = _home(tmp_path)
    directory = _workflow(home, IMPORTED)
    fakes = container.fakes(
        TreesRoot(tmp_path / "trees"), files={"src/a.txt": b"one\n"}, agent=_unwanted
    )

    before = digests(directory)
    await api.run(fakes.services, PROJECT, IMPORTED, RunLabel("first"), (), home=home)
    once = digests(directory)
    await api.run(fakes.services, PROJECT, IMPORTED, RunLabel("second"), (), home=home)
    twice = digests(directory)

    assert (directory / "__pycache__").is_dir(), (
        f"no bytecode was written under {directory}, so this test measured nothing: the exclusion "
        f"it exists to prove was never reached. Either the import did not happen or this "
        f"interpreter is not writing `.pyc` files, and neither is a green line."
    )
    assert tuple(before) == _WRITTEN
    assert before == once == twice

# --- the same answer for files that are not on disk yet, and one hash for all of them ------------

def test_files_digested_in_memory_answer_what_the_directory_holding_them_answers(
    tmp_path: Path,
) -> None:
    """The walk's twin for a download, compared with the walk over those very files written out.

    Nested paths, a name outside ASCII, bytecode at two depths and a file that is merely called
    `__pycache__` - the walk passes over a directory of that name and not a file, and the twin has
    to draw the line in the same place. Order is compared as well as content, both being sorted.
    """
    files = {
        "__init__.py": b"from agl.sdk import Run, workflow\n",
        "prompts/caf\u00e9.md": b"# review\n",
        "__pycache__/__init__.cpython-314.pyc": b"compiled",
        "flows/__pycache__/review.cpython-314.pyc": b"compiled too",
        "flows/review.py": b"REVIEW = 1\n",
        "notes/__pycache__": b"a file, whatever its name says",
        "empty.md": b"",
    }
    for name, content in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_bytes(content)

    assert list(digested(files).items()) == list(digests(tmp_path).items())
    assert "notes/__pycache__" in digested(files)

def test_the_content_hash_is_one_answer_whatever_order_its_map_was_built_in() -> None:
    measured = digested({"b.py": b"b\n", "a.py": b"a\n", "c/d.md": b"d\n"})

    assert content_hash(dict(reversed(list(measured.items())))) == content_hash(measured)

def test_the_content_hash_of_one_known_tree_is_the_answer_it_has_always_been() -> None:
    """The scheme held still, because a provenance file keeps its answer across upgrades of AGL.

    A byte moved in how one file is digested or in how the digests are run together gives every
    workflow `agl get` has placed a hash other than the one its provenance file recorded, and every
    one of them would read as edited. So the answer is written out rather than derived here.
    """
    files = {
        "__init__.py": b"from agl.sdk import Run, workflow\n",
        "prompts/review.md": b"# review\n",
    }

    assert content_hash(digested(files)) == (
        "7dcb92bcb8cc0d7f7e9c63ae13180a486a80062e7c0b0b8e4b9baf722cd12c7c"
    )
