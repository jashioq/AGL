from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Final
from agl import api
from agl.config import container, registry
from agl.config.container import Press, ScriptedTerminal
from agl.ports.agent import AgentTask, StopReason
from agl.ports.errors import InputError
from agl.ports.home_layout import RunScope
from agl.ports.ids import Namespace, ProjectName, RunLabel, StepName
from agl.ports.run import JsonValue
from agl.ports.store import Store
from agl.ports.terminal import Terminal
from agl.ports.tree_layout import TreesRoot
from agl.sdk._engine.journal import Entry
from agl.sdk.testing import Agent, Call, Reply
from agl.sdk.workflow import Run, Workflow

__all__ = [
    "Agent",
    "AgentTask",
    "Call",
    "Harness",
    "Press",
    "Recorded",
    "Reply",
    "ScriptedTerminal",
    "StopReason",
    "a_run",
    "answering",
    "harness",
    "over",
    "reports",
]

_PROJECT: Final = "project"
_LABEL: Final = "test"

_TREES: Final = "trees"

_BASE: Final = "4a91c07f2b3e8d15c6a0f31d8e2b47c9a6013f5e"

class _Interrupted(BaseException):
    ...

@dataclass(frozen=True, slots=True)
class Recorded:
    step: str

    namespace: str | None

    value: JsonValue

class _Ledger(Store):
    def __init__(self, store: Store) -> None:
        self._store = store
        self.recorded: list[Recorded] = []

        self._after: int | None = None
        self._written = 0

    def interrupt_after(self, steps: int | None) -> None:
        self._after = steps
        self._written = 0

    async def read_record(self, scope: RunScope) -> dict[str, JsonValue] | None:
        return await self._store.read_record(scope)

    async def write_record(self, scope: RunScope, value: Mapping[str, JsonValue]) -> None:
        await self._store.write_record(scope, value)

    async def read_entry(
        self, scope: RunScope, step: StepName, digest: str
    ) -> dict[str, JsonValue] | None:
        return await self._store.read_entry(scope, step, digest)

    async def write_entry(
        self, scope: RunScope, step: StepName, digest: str, value: Mapping[str, JsonValue]
    ) -> None:
        await self._store.write_entry(scope, step, digest, value)
        self.recorded.append(
            Recorded(
                step=str(step),
                namespace=_innermost(scope.namespaces),
                value=Entry.from_json(value).value,
            )
        )
        self._written += 1
        if self._after is not None and self._written >= self._after:
            raise _Interrupted(
                f"the harness interrupted this run after {self._written} step(s) recorded, which "
                f"is what `interrupt_after={self._after}` asked for"
            )

    async def namespaces(self, scope: RunScope) -> tuple[Namespace, ...]:
        return await self._store.namespaces(scope)

    async def remove(self, scope: RunScope) -> None:
        await self._store.remove(scope)

@dataclass(frozen=True, slots=True)
class Harness:
    fakes: container.FakeServices

    scope: RunScope

    _ledger: _Ledger = field(repr=False, compare=False)

    @property
    def recorded(self) -> tuple[Recorded, ...]:
        return tuple(self._ledger.recorded)

    async def run[P](
        self,
        workflow: Workflow[P],
        *flags: str,
        base_ref: str | None = None,
        interrupt_after: int | None = None,
    ) -> None:
        point = _resolvable(workflow)
        with self._interrupting(interrupt_after):
            await api.run(
                self.fakes.services,
                self.scope.project,
                point.name,
                self.scope.label,
                flags,
                base_ref=base_ref,
                points=(point,),
            )

    async def resume[P](
        self, workflow: Workflow[P], *, interrupt_after: int | None = None
    ) -> None:
        point = _resolvable(workflow)
        with self._interrupting(interrupt_after):
            await api.resume(
                self.fakes.services, self.scope.project, self.scope.label, points=(point,)
            )

    @contextmanager
    def _interrupting(self, after: int | None) -> Iterator[None]:
        if after is not None and after < 1:
            raise InputError(
                f"`interrupt_after={after}` asks for a run interrupted before its first step has "
                f"recorded anything, which is a run that did nothing - there would be no entry to "
                f"replay and a resume would walk the whole workflow again. The smallest one that "
                f"leaves something on the ledger is 1"
            )
        self._ledger.interrupt_after(after)
        try:
            yield
        except _Interrupted:
            return
        except BaseExceptionGroup as group:
            _, rest = group.split(_Interrupted)
            if rest is not None:
                raise rest from group
        finally:
            self._ledger.interrupt_after(None)

def harness(
    where: Path,
    *,
    agent: Agent | None = None,
    files: Mapping[str, bytes] | None = None,
    build: str = container.FAKE_BUILD,
    terminal: Terminal | None = None,
    project: str = _PROJECT,
    label: str = _LABEL,
) -> Harness:
    fakes = container.fakes(TreesRoot(where / _TREES), files=files, build=build, agent=agent)
    if terminal is not None:
        fakes = fakes.with_terminal(terminal)
    return over(fakes, project=project, label=label)

def over(
    fakes: container.FakeServices,
    *,
    project: str = _PROJECT,
    label: str = _LABEL,
) -> Harness:
    ledger = _Ledger(fakes.store)
    return Harness(
        fakes=fakes.with_store(ledger),
        scope=RunScope(ProjectName(project), RunLabel(label)),
        _ledger=ledger,
    )

def answering(responses: Sequence[Press | int] = ()) -> ScriptedTerminal:
    return container.answering(responses)

def a_run[P](
    harness: Harness,
    params: P,
    *,
    base: str = _BASE,
    activity: str | None = None,
) -> Run[P]:
    run: Run[P] = Run(
        params=params, services=harness.fakes.services, scope=harness.scope, base=base
    )
    reports(run, activity)
    return run

def reports(run: Run[object], activity: str | None) -> None:
    run._steps._activity = activity

def _innermost(namespaces: Sequence[Namespace]) -> str | None:
    if not namespaces:
        return None
    return str(namespaces[-1])

def _resolvable[P](workflow: Workflow[P]) -> EntryPoint:
    where = workflow.fn.__module__
    named = workflow.fn.__qualname__
    if "." in named:
        raise InputError(
            f"the workflow declared as {named!r} is inside something else, so there is no module "
            f"attribute for an entry point to name. A workflow is registered as "
            f"`<module>:<name>`, and the harness resolves it the way an installed one is "
            f"resolved, so declare it at the top level of its module"
        )
    point = EntryPoint(name=named, value=f"{where}:{named}", group=registry.GROUP)
    resolved: Workflow[object] = registry.load((point,), named, Workflow)
    if resolved is not workflow:
        raise InputError(
            f"the workflow handed to the harness is not what {point.value!r} resolves to, and that "
            f"is the entry point its own module and function name compose. `@workflow` returns the "
            f"`Workflow` and the decorated name is what an entry point points at, so this happens "
            f"when the decorated function is bound to a name other than its own. Register it as "
            f"`{where}:<the attribute it is bound to>` and give the harness that same object"
        )
    return point
