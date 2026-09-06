from pathlib import Path
from typing import Final
from agl.ports.sync import Syncer, SyncOutcome

__all__ = ["FakeSyncer"]

_AGREES_SYNCED: Final = 0
_AGREES_REFUSED: Final = 1

_UNSCRIPTED_SYNC: Final = SyncOutcome(synced=True, status=_AGREES_SYNCED, output="")
_UNSCRIPTED_REFUSAL: Final = SyncOutcome(synced=False, status=_AGREES_REFUSED, output="")

class FakeSyncer(Syncer):
    def __init__(self, *, unscripted_syncs: bool = True) -> None:
        self._scripted: dict[Path, SyncOutcome] = {}
        self._unscripted = _UNSCRIPTED_SYNC if unscripted_syncs else _UNSCRIPTED_REFUSAL

    def answers(
        self, workspace: Path, *, synced: bool, status: int | None = None, output: str = ""
    ) -> None:
        reported = status if status is not None else (_AGREES_SYNCED if synced else _AGREES_REFUSED)
        self._scripted[workspace] = SyncOutcome(synced=synced, status=reported, output=output)

    async def sync(self, workspace: Path) -> SyncOutcome:
        return self._scripted.get(workspace, self._unscripted)
