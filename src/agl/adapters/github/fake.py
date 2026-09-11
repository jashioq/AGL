from collections.abc import Mapping
from typing import Final
from agl.ports.errors import AglError, NotFoundError
from agl.ports.fetch import (
    FetchAnswer,
    FetchedFile,
    FetchedWorkflow,
    Fetcher,
    RefusedWorkflow,
    Resolution,
    ResolvedRef,
    UnresolvedRef,
)
from agl.ports.get_request import Fetch, RepositoryAtRef, RequestedWorkflow

__all__ = ["FAKE_COMMIT", "FakeFetcher"]

FAKE_COMMIT: Final = "0123456789abcdef0123456789abcdef01234567"

_SEPARATOR: Final = "/"

class FakeFetcher(Fetcher):
    def __init__(self) -> None:
        self._trees: dict[RepositoryAtRef, tuple[str, Mapping[str, FetchedFile]]] = {}
        self._refusals: dict[RepositoryAtRef, AglError] = {}
        self._asked: list[Fetch] = []
        self._looked_up: list[RepositoryAtRef] = []

    def serves(
        self,
        repository: RepositoryAtRef,
        files: Mapping[str, FetchedFile],
        *,
        commit: str = FAKE_COMMIT,
    ) -> None:
        self._refusals.pop(repository, None)
        self._trees[repository] = (commit, dict(files))

    def refuses(self, repository: RepositoryAtRef, refusal: AglError) -> None:
        self._trees.pop(repository, None)
        self._refusals[repository] = refusal

    @property
    def fetched(self) -> tuple[Fetch, ...]:
        return tuple(self._asked)

    @property
    def resolved(self) -> tuple[RepositoryAtRef, ...]:
        return tuple(self._looked_up)

    async def fetch(self, fetch: Fetch) -> tuple[FetchAnswer, ...]:
        self._asked.append(fetch)
        refusal = self._refusal(fetch.repository)
        if refusal is not None:
            return tuple(RefusedWorkflow(workflow, refusal) for workflow in fetch.workflows)
        commit, tree = self._trees[fetch.repository]
        return tuple(_answer(workflow, commit, tree) for workflow in fetch.workflows)

    async def resolve(self, repository: RepositoryAtRef) -> Resolution:
        self._looked_up.append(repository)
        refusal = self._refusal(repository)
        if refusal is not None:
            return UnresolvedRef(repository, refusal)
        commit, _ = self._trees[repository]
        return ResolvedRef(repository, commit)

    def _refusal(self, repository: RepositoryAtRef) -> AglError | None:
        refusal = self._refusals.get(repository)
        if refusal is None and repository not in self._trees:
            return NotFoundError(f"the fake fetcher serves no repository {repository}")
        return refusal

def _answer(
    workflow: RequestedWorkflow, commit: str, tree: Mapping[str, FetchedFile]
) -> FetchAnswer:
    within = workflow.directory + _SEPARATOR
    files = {
        path.removeprefix(within): held for path, held in tree.items() if path.startswith(within)
    }
    if files:
        return FetchedWorkflow(workflow, commit, files)
    what = "is a file" if workflow.directory in tree else "is not there"
    return RefusedWorkflow(
        workflow,
        NotFoundError(f"{workflow.directory!r} {what} in the fake's {workflow.repository}"),
    )
