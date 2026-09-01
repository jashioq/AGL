from pathlib import Path
from typing import Final
from agl.ports.verifier import Verifier, VerifierOutcome

__all__ = ["FakeVerifier"]

_AGREES_PASSED: Final = 0
_AGREES_FAILED: Final = 1

_UNSCRIPTED_PASS: Final = VerifierOutcome(passed=True, status=_AGREES_PASSED, output="")
_UNSCRIPTED_FAIL: Final = VerifierOutcome(passed=False, status=_AGREES_FAILED, output="")

class FakeVerifier(Verifier):
    def __init__(self, *, unscripted_passes: bool = True) -> None:
        self._scripted: dict[str, VerifierOutcome] = {}
        self._unscripted = _UNSCRIPTED_PASS if unscripted_passes else _UNSCRIPTED_FAIL

    def answers(
        self, command: str, *, passed: bool, status: int | None = None, output: str = ""
    ) -> None:
        reported = status if status is not None else (_AGREES_PASSED if passed else _AGREES_FAILED)
        self._scripted[command] = VerifierOutcome(passed=passed, status=reported, output=output)

    async def verify(self, command: str, workdir: Path) -> VerifierOutcome:
        return self._scripted.get(command, self._unscripted)
