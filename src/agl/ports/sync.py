from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

__all__ = ["SyncOutcome", "Syncer"]

@dataclass(frozen=True, slots=True)
class SyncOutcome:
    synced: bool

    status: int

    output: str

# What a sync installs is what the workflows declare and never the workflows themselves. A workflow
# is imported from the workspace's own `workflows/` directory, and `config/workspace_path.py`
# appends the venv's site-packages *ahead* of it - so an installed copy of a workflow would resolve
# in front of the source the operator is editing.
class Syncer(ABC):
    @abstractmethod
    async def sync(self, workspace: Path) -> SyncOutcome:
        """Install what the workspace's workflows declare, and report what the installer said.

        :param workspace: the directory holding the workspace's project file, never a workflow's own
        :return: the verdict and the text reaching it; a refused sync is this rather than a raise
        :raises NotFoundError: this is no workspace - there is no project file here to install from
        :raises UpstreamUnavailable: where the installer could not be started, so nothing was tried
        :raises UpstreamUnexpected: the installer was started and answered in terms it cannot read
        """
        ...
