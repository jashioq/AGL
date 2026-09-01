"""`agl.adapters.git` keeps a refusal apart from an outage, over the one function that decides it.

`_translated` in `git/_trees.py` is four lines with one branch in them: a `PermissionError` becomes
`DeniedError` and every other `OSError` becomes `UpstreamUnavailable`. That branch is not a matter
of wording. `ports/errors.py`'s `EXIT_CODES` maps `DeniedError` to **5** and `UpstreamError` to
**6**, and the two mean opposite things to whoever reads them: 5 is *this will not work until you
change something* - a checkout the user may not delete, a trees root under a directory they do not
own - and 6 is *the same call may succeed later*. An adapter that answered 6 for a permission sends
a person to retry a command that will refuse them again for as long as the permission stands.

## Why this file exists at all, and why it is named for the invariant

`_translated` used to be written twice, byte for byte, in `git/_trees.py` and `git/_working.py`.
Now `_trees.py` holds it and `_working.py` spends it - a sibling module inside one adapter, which
`ARCHITECTURE.md`'s "No general subprocess helper" names as the one place a helper can be shared
for free. **The fold is what makes this test cheap enough to write**: one assertion now covers
both modules, where before it would have covered one definition and left an identical twin
unasserted next to it. Banking that is the point of having folded them.

Named for the invariant rather than for a module, because the rule is about the package: a test
asserting it from inside `test_git_fake.py` would be a test about the fake that is not, which is
`test_filesystem_no_lock.py`'s reason for its own name. `tests/` carries no `__init__.py` - see
`tests/conftest.py` for why it must not - so pytest's module names are the bare filenames and this
one has to be distinct from the eight other `test_git_*.py`.

## Both call sites, because one function with two callers is what is being asserted

Two provocations per class, deliberately: `shutil.rmtree` reaches `_translated` from `_trees.py`'s
own `delete`, and `Path.iterdir` reaches it from `_working.py`'s `_gather`. A version of this file
that provoked only the first would pass against a `git/_working.py` that had quietly grown a second
copy of the function back, translating a refusal as an outage on the half of the package this file
never touched.

`delete` is reached through the fake provider rather than the real one, and the choice is not a
compromise: `_trees.delete` is the *same* function `GitWorkspaceProvider.remove` calls - the two
providers differ in what they do about git's registry afterwards and not in this - and
`_working.py` is reached from the fake and from nowhere else, so one instrument reaches both call
sites and a real repository would buy nothing here but a subprocess.

## The technique, and the hazard it is avoiding

The builtin is raised into the call rather than provoked by a `chmod`, following
`tests/adapters/test_filesystem_store.py::test_a_refusal_from_the_filesystem_surfaces_as_denied`,
which does the same thing to `os.replace` and `Path.read_text` for the same branch of the
filesystem store's own translator. `chmod 000` does nothing as root and this suite has no promise
about who runs it - `tests/config/test_toml_file.py` records that gotcha in as many words and
answers it by choosing a different provocation, which is what this file does too. What is under
test is one `isinstance` check, and no filesystem *state* produces `PermissionError` reliably
enough to reach it, so the builtin arrives the way the branch reads it.
"""

import shutil
from pathlib import Path
from typing import Final
import pytest
from agl.adapters.git.fake import FakeRepository, FakeWorkspaceProvider
from agl.ports.errors import DeniedError, UpstreamUnavailable
from agl.ports.ids import RunLabel
from agl.ports.tree_layout import TreesRoot
from agl.ports.workspace import Workspace, WorkspaceProvider

# Module-level tests inherit no marker from anywhere, and `asyncio_mode = "strict"` turns a missing
# one into a test pytest silently skips - which is how a file like this passes having run nothing.
pytestmark = pytest.mark.asyncio

LABEL: Final = RunLabel("auth")

SOURCE: Final = "agl-denied/source.txt"
BODY: Final = b"the state a run is cut from\n"

# The two errno values, as the two arms read them. 13/EACCES is what the kernel answers for a
# permission and is the only one that reaches `DeniedError`; 5/EIO is an ordinary failure standing
# in for every other `OSError`, chosen because nothing about it is a permission.
REFUSED: Final = (13, "Permission denied")
BROKEN: Final = (5, "Input/output error")

@pytest.fixture
def repository() -> FakeRepository:
    """A fresh in-memory repository, seeded with one file and on its default branch."""
    return FakeRepository({SOURCE: BODY})

@pytest.fixture
def provider(repository: FakeRepository, tmp_path: Path) -> WorkspaceProvider:
    """A fake provider over that repository and an empty trees root."""
    return FakeWorkspaceProvider(repository, TreesRoot(tmp_path / "trees"))

async def test_a_permission_is_denied_and_every_other_os_error_is_an_outage(
    repository: FakeRepository, provider: WorkspaceProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One `isinstance` check, asserted from both modules that spend it, in both directions.

    The checkout is provisioned first and monkeypatched after, so that the calls under test are
    the first ones either stand-in ever sees and a failure here is the provocation rather than the
    setup.

    The class is what is asserted and the sentence is not, because the class is what `EXIT_CODES`
    keys on: a `DeniedError` reported as `UpstreamUnavailable` is exit 6 for a state no retry will
    change, and the person reading it runs the command again instead of fixing the permission. A
    `match=` on the prose would additionally fail for a reword that changed no exit code, which is
    a different assertion than the one worth having here.

    Both directions, because half of this is worthless. A translator that answered `DeniedError`
    for everything would keep the assertion below green on its permission arm and would call a
    disk fault a refusal - so the same two calls are provoked with an ordinary `OSError` and have
    to come back as the other class.
    """
    workspace: Workspace = await provider.open(
        LABEL, None, repository.resolve(repository.default_ref)
    )

    def refuse_tree(path: object, **options: object) -> None:
        raise PermissionError(*REFUSED, str(path))

    def refuse_listing(self: Path) -> list[Path]:
        raise PermissionError(*REFUSED, str(self))

    monkeypatch.setattr(shutil, "rmtree", refuse_tree)
    monkeypatch.setattr(Path, "iterdir", refuse_listing)

    with pytest.raises(DeniedError):
        await workspace.commit_all("what _working.py could not read")
    with pytest.raises(DeniedError):
        await provider.remove(LABEL, None)

    def break_tree(path: object, **options: object) -> None:
        raise OSError(*BROKEN, str(path))

    def break_listing(self: Path) -> list[Path]:
        raise OSError(*BROKEN, str(self))

    monkeypatch.setattr(shutil, "rmtree", break_tree)
    monkeypatch.setattr(Path, "iterdir", break_listing)

    with pytest.raises(UpstreamUnavailable):
        await workspace.commit_all("what _working.py could not read")
    with pytest.raises(UpstreamUnavailable):
        await provider.remove(LABEL, None)
