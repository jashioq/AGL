
import asyncio
from collections.abc import Callable

from agl.ports.errors import InternalError
from agl.ports.history import History
from agl.ports.home_layout import RunScope
from agl.ports.integration import Conflict, IntegrationOutcome, Integrator
from agl.ports.verifier import Verifier, VerifierOutcome
from agl.ports.workspace import Workspace
from agl.sdk._engine.journal import Journal
from agl.sdk._engine.services import Services
from agl.sdk._engine.steps import Steps

__all__ = ["Integration", "Leases", "integrate"]


class Leases:

    def __init__(self) -> None:
        self._locks: dict[RunScope, asyncio.Lock] = {}
        self._live: dict[RunScope, Lease] = {}

    async def claim(self, target: RunScope, journal: Journal) -> Lease:
        lock = self._locks.get(target)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[target] = lock
        await lock.acquire()
        try:
            admit = await journal.exclude_steps()
        except BaseException:
            lock.release()
            raise
        lease = Lease(target, lock, admit, self._returned)
        self._live[target] = lease
        return lease

    def release_all(self) -> None:
        for lease in tuple(self._live.values()):
            lease.release()

    def _returned(self, lease: Lease) -> None:
        if self._live.get(lease.target) is lease:
            del self._live[lease.target]


class Lease:

    def __init__(
        self,
        target: RunScope,
        lease: asyncio.Lock,
        admit: Callable[[], None],
        returned: Callable[[Lease], None],
    ) -> None:
        self.target = target
        self._lease = lease
        self._admit = admit
        self._returned = returned
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._admit()
        self._lease.release()
        self._returned(self)


class Integration:

    def __init__(
        self,
        *,
        source: Workspace,
        target: Workspace,
        journal: Journal,
        integrator: Integrator,
        history: History,
        verifier: Verifier,
        build: str,
        before: str,
        lease: Lease,
    ) -> None:
        self._source = source
        self._target = target
        self._journal = journal
        self._integrator = integrator
        self._history = history
        self._verifier = verifier
        self._build = build
        self._before = before
        self._lease = lease
        self._head: str | None = None
        self._conflict: Conflict | None = None
        self._verdict: VerifierOutcome | None = None
        self._settled = False

    @property
    def head(self) -> str | None:
        return self._head

    @property
    def conflict(self) -> Conflict | None:
        return self._conflict

    @property
    def conflicted(self) -> bool:
        return self._conflict is not None

    @property
    def verdict(self) -> VerifierOutcome | None:
        return self._verdict

    async def retry(self) -> None:
        if self._settled:
            raise InternalError(_nothing_to_retry(self._head))
        outcome: IntegrationOutcome | None = None
        try:
            outcome = await self._integrator.retry(self._target)
        except InternalError:
            outcome = None
        if outcome is None:
            outcome = await self._integrator.land(self._source, self._target)
        await self._concluded(outcome, again=False)

    async def abort(self) -> None:
        if self._settled:
            return
        await self._integrator.abort(self._target)
        self._settle()

    async def _concluded(self, outcome: IntegrationOutcome, *, again: bool) -> None:
        if outcome.conflicted:
            self._conflict = outcome.conflict
            self._head = None
            self._verdict = None
            return
        head = outcome.head
        if head is None:
            raise InternalError(
                "an integration outcome reports neither a landing nor a conflict, which the type "
                "refuses to be constructed as - so this is not an adapter's answer, it is ours"
            )
        if not await self._history.contains(await self._source.head(), head):
            if again:
                raise InternalError(_still_not_in(self._source.branch, self._target.branch, head))
            await self._concluded(
                await self._integrator.land(self._source, self._target), again=True
            )
            return

        if not await self._gated():
            return

        self._journal.advance(head)
        self._head = head
        self._conflict = None
        self._settle()

    async def _gated(self) -> bool:
        verdict = await self._verifier.verify(self._build, self._target.path)
        self._verdict = verdict
        if verdict.passed:
            return True
        await self._target.restore(self._before)
        self._conflict = Conflict(
            paths=(),
            summary=_gate_refused(self._build, verdict.status, self._target.branch, self._before),
        )
        self._head = None
        return False

    def _settle(self) -> None:
        self._settled = True
        self._lease.release()


async def integrate(
    *,
    source: Steps,
    target: Steps,
    address: RunScope,
    services: Services,
    leases: Leases,
) -> Integration:
    _, child = await source.landing()
    journal, parent = await target.landing()
    lease = await leases.claim(address, journal)
    try:
        integration = Integration(
            source=child,
            target=parent,
            journal=journal,
            integrator=services.integrator,
            history=services.history,
            verifier=services.verifier,
            build=services.build,
            before=await parent.head(),
            lease=lease,
        )
        await integration._concluded(
            await services.integrator.land(child, parent), again=False
        )
    except BaseException:
        lease.release()
        raise
    return integration


def _nothing_to_retry(head: str | None) -> str:
    ended = (
        f"it landed, and the target is at {head!r}"
        if head is not None
        else "it was aborted, and the hold was released"
    )
    return (
        f"this integration is over - {ended} - so there is nothing left to try again. `retry` is "
        f"for an outcome that is still conflicted and still holding its lease; once one has "
        f"settled, the lease is back, the parent's chain has been decided, and a retry would be "
        f"acting on a landing nothing is holding. A second `abort` is the tolerant one and says "
        f"nothing; this is the asymmetry `ports/integration.py` pins for its own two verbs"
    )


def _gate_refused(command: str, status: int, target: str, before: str) -> str:
    return (
        f"the build gate refused this landing. {target!r} took the work with no textual collision, "
        f"and then {command!r} ran in that tree and ended with status {status}, so the landing was "
        f"undone: {target!r} is back at {before!r} and its working tree holds nothing the build "
        f"left behind. There is no list of colliding files because there is nothing to list - what "
        f"failed is the combination rather than any one file, which is the semantic conflict this "
        f"gate exists to catch and the reason two pieces of work that each build alone can still "
        f"be refused together. The build's own output is on the outcome, beside this conflict"
    )


def _still_not_in(source: str, target: str, head: str) -> str:
    return (
        f"{target!r} is at {head!r} after landing {source!r} into it a second time, and that state "
        f"still does not contain {source!r}. The first answer was somebody else's landing being "
        f"concluded - a resumed run finds a hold it did not take - which this re-landing is "
        f"the answer to - so a second one that still leaves the work out is not a case to try "
        f"again through, it is AGL and the integrator disagreeing about what landed. Nothing has "
        f"been advanced: the parent's chain still names the state it did before this integration"
    )
